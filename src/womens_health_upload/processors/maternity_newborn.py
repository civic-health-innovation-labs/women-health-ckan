"""Process NHS Maternity Statistics newborn summary tables."""

import warnings
from pathlib import Path

import pandas as pd

SOURCE_FILE = Path(
    "data/raw/nhs_maternity/"
    "hosp-epis-stat-mat-summary-tables-2425.xlsx"
)

REPORT_8_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-newborn-characteristics-summary-report-8.csv"
)

REPORT_8_SHEET_NAME = "Summary report 8"

BIRTHWEIGHT_BANDS = [
    ("1499 and under", 0, 1499),
    ("1500 to 2499", 1500, 2499),
    ("2500 to 2999", 2500, 2999),
    ("3000 to 3499", 3000, 3499),
    ("3500 to 3999", 3500, 3999),
    ("4000 and over", 4000, 7000),
]

REPORT_9_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-newborn-characteristics-summary-report-9.csv"
)

REPORT_9_SHEET_NAME = "Summary report 9"

APGAR_SCORE_GROUPS = [
    ("0 to 6", 0, 6),
    ("7 to 10", 7, 10),
]

def process_summary_report_8(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_8_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract and validate recorded birthweight percentages."""

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Source workbook was not found: {source_path}"
        )

    warnings.filterwarnings(
        "ignore",
        message="Cannot parse header or footer",
        category=UserWarning,
    )

    raw = pd.read_excel(
        source_path,
        sheet_name=REPORT_8_SHEET_NAME,
        header=None,
    )

    normalized = raw.apply(
        lambda column: column.fillna("").astype(str).str.strip()
    )

    percentage_rows = normalized.index[
        normalized.eq("Percentage of total deliveries").any(axis=1)
    ].tolist()

    if len(percentage_rows) != 1:
        raise ValueError(
            "Expected exactly one 'Percentage of total deliveries' "
            f"row in {REPORT_8_SHEET_NAME}; found "
            f"{len(percentage_rows)}."
        )

    percentage_row = percentage_rows[0]
    band_row = percentage_row - 1
    expected_labels = [band[0] for band in BIRTHWEIGHT_BANDS]

    band_columns = [
        column
        for column in normalized.columns
        if normalized.at[band_row, column] in expected_labels
    ]

    observed_labels = [
        normalized.at[band_row, column]
        for column in band_columns
    ]

    if observed_labels != expected_labels:
        raise ValueError(
            "The birthweight bands differ from the expected source "
            f"structure. Found: {observed_labels}"
        )

    percentages = pd.to_numeric(
        raw.loc[percentage_row, band_columns],
        errors="raise",
    )

    if percentages.isna().any():
        raise ValueError(
            "One or more birthweight percentages are missing."
        )

    if ((percentages < 0) | (percentages > 100)).any():
        raise ValueError(
            "Birthweight percentages must be between 0 and 100."
        )

    if ((percentages % 1) != 0).any():
        raise ValueError(
            "Birthweight percentages must be whole numbers."
        )

    records = []

    for order, ((label, minimum, maximum), percentage) in enumerate(
        zip(BIRTHWEIGHT_BANDS, percentages, strict=True),
        start=1,
    ):
        records.append(
            {
                "reporting_period": "2024-25",
                "birthweight_band": label,
                "birthweight_band_order": order,
                "minimum_birthweight_grams": minimum,
                "maximum_birthweight_grams": maximum,
                "percentage_of_deliveries_with_recorded_birthweight": int(
                    percentage
                ),
                "denominator_scope": (
                    "Deliveries with a recorded baby birthweight"
                ),
                "birthweight_definition": (
                    "Weight of the baby in grams immediately after birth. "
                    "Only the first birth record is considered when a baby "
                    "appears on multiple birth delivery records."
                ),
                "unknown_birthweight_note": (
                    "Birthweights above 7000 grams or null are classified "
                    "as unknown and excluded from this analysis."
                ),
                "geography": "England",
                "unit": "percent",
                "source": (
                    "Hospital Episode Statistics (HES), NHS England"
                ),
                "source_release": (
                    "NHS Maternity Statistics, 2024-25"
                ),
                "source_file": source_path.name,
                "source_sheet": REPORT_8_SHEET_NAME,
            }
        )

    result = pd.DataFrame.from_records(records)

    if len(result) != 6:
        raise ValueError(
            f"Expected 6 output rows; produced {len(result)}."
        )

    if result["birthweight_band"].duplicated().any():
        raise ValueError("Duplicate birthweight bands were produced.")

    percentage_total = result[
        "percentage_of_deliveries_with_recorded_birthweight"
    ].sum()

    if not 99 <= percentage_total <= 101:
        raise ValueError(
            "Birthweight percentages should total approximately 100; "
            f"found {percentage_total}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp")
    result.to_csv(temporary_path, index=False)
    temporary_path.replace(output_path)

    print(f"Created: {output_path}")
    print(f"Rows: {len(result)}")

    return result

def process_summary_report_9(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_9_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract and validate five-minute Apgar score statistics."""

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Source workbook was not found: {source_path}"
        )

    warnings.filterwarnings(
        "ignore",
        message="Cannot parse header or footer",
        category=UserWarning,
    )

    raw = pd.read_excel(
        source_path,
        sheet_name=REPORT_9_SHEET_NAME,
        header=None,
    )

    normalized = raw.apply(
        lambda column: column.fillna("").astype(str).str.strip()
    )

    header_rows = normalized.index[
        normalized.eq("Apgar score group").any(axis=1)
    ].tolist()

    if len(header_rows) != 1:
        raise ValueError(
            "Expected exactly one Apgar score header row in "
            f"{REPORT_9_SHEET_NAME}; found {len(header_rows)}."
        )

    header_row = header_rows[0]

    group_columns = normalized.columns[
        normalized.loc[header_row].eq("Apgar score group")
    ].tolist()

    number_columns = normalized.columns[
        normalized.loc[header_row].eq("Number of babies")
    ].tolist()

    percentage_columns = [
        column
        for column in normalized.columns
        if normalized.at[header_row, column].startswith("Per cent")
    ]

    if (
        len(group_columns) != 1
        or len(number_columns) != 1
        or len(percentage_columns) != 1
    ):
        raise ValueError(
            "Could not identify the Apgar group, count and percentage "
            "columns uniquely."
        )

    group_column = group_columns[0]
    number_column = number_columns[0]
    percentage_column = percentage_columns[0]

    expected_labels = [group[0] for group in APGAR_SCORE_GROUPS]
    group_rows = {}

    for label in expected_labels:
        rows = normalized.index[
            normalized[group_column].eq(label)
        ].tolist()

        if len(rows) != 1:
            raise ValueError(
                f"Expected exactly one row for Apgar group '{label}'; "
                f"found {len(rows)}."
            )

        group_rows[label] = rows[0]

    missing_rows = normalized.index[
        normalized[group_column].str.startswith(
            "Missing Value / Value outside reporting parameters"
        )
    ].tolist()

    total_rows = normalized.index[
        normalized[group_column].eq("Total")
    ].tolist()

    if len(missing_rows) != 1 or len(total_rows) != 1:
        raise ValueError(
            "Expected exactly one missing/invalid row and one total row."
        )

    counts = [
        pd.to_numeric(
            raw.at[group_rows[label], number_column],
            errors="raise",
        )
        for label in expected_labels
    ]

    proportions = [
        pd.to_numeric(
            raw.at[group_rows[label], percentage_column],
            errors="raise",
        )
        for label in expected_labels
    ]

    missing_count = pd.to_numeric(
        raw.at[missing_rows[0], number_column],
        errors="raise",
    )

    total_count = pd.to_numeric(
        raw.at[total_rows[0], number_column],
        errors="raise",
    )

    all_counts = [*counts, missing_count, total_count]

    if any(pd.isna(value) for value in all_counts):
        raise ValueError("One or more Apgar counts are missing.")

    if any(value < 0 or value % 1 != 0 for value in all_counts):
        raise ValueError(
            "Apgar counts must be non-negative whole numbers."
        )

    if any(pd.isna(value) for value in proportions):
        raise ValueError(
            "One or more valid-score proportions are missing."
        )

    if any(value < 0 or value > 1 for value in proportions):
        raise ValueError(
            "Apgar proportions must be between zero and one."
        )

    if abs(sum(proportions) - 1) > 0.001:
        raise ValueError(
            "Valid Apgar score proportions do not total one."
        )

    valid_count = int(sum(counts))
    missing_count = int(missing_count)
    total_count = int(total_count)

    if valid_count + missing_count != total_count:
        raise ValueError(
            "Valid and missing/invalid Apgar counts do not reconcile "
            f"to the total: {valid_count} + {missing_count} != "
            f"{total_count}."
        )

    records = []

    for order, (
        (label, minimum, maximum),
        count,
        proportion,
    ) in enumerate(
        zip(
            APGAR_SCORE_GROUPS,
            counts,
            proportions,
            strict=True,
        ),
        start=1,
    ):
        records.append(
            {
                "reporting_period": "2024-25",
                "apgar_score_group": label,
                "apgar_score_group_order": order,
                "minimum_apgar_score": minimum,
                "maximum_apgar_score": maximum,
                "number_of_babies": int(count),
                "percentage_of_babies_with_valid_apgar_score": round(
                    float(proportion) * 100,
                    1,
                ),
                "total_live_term_babies": total_count,
                "valid_apgar_score_babies": valid_count,
                "missing_or_invalid_apgar_score_babies": missing_count,
                "apgar_measurement_timing": (
                    "Five minutes after birth; earliest recorded "
                    "five-minute Apgar value."
                ),
                "population_scope": (
                    "Distinct live-born term babies with gestation "
                    "length between 259 and 315 days."
                ),
                "percentage_denominator": (
                    "Live-born term babies with a valid Apgar score "
                    "between 0 and 10."
                ),
                "rounding_note": (
                    "Baby counts are rounded to the nearest 5. Counts "
                    "between 1 and 7 are rounded to 5. Percentages are "
                    "calculated from rounded counts."
                ),
                "geography": "England",
                "count_unit": "babies",
                "percentage_unit": "percent",
                "source": (
                    "Maternity Services Data Set (MSDS), NHS England"
                ),
                "source_release": (
                    "NHS Maternity Statistics, 2024-25"
                ),
                "source_file": source_path.name,
                "source_sheet": REPORT_9_SHEET_NAME,
            }
        )

    result = pd.DataFrame.from_records(records)

    if len(result) != 2:
        raise ValueError(
            f"Expected 2 output rows; produced {len(result)}."
        )

    if result["apgar_score_group"].duplicated().any():
        raise ValueError("Duplicate Apgar score groups were produced.")

    percentage_total = result[
        "percentage_of_babies_with_valid_apgar_score"
    ].sum()

    if abs(percentage_total - 100) > 0.1:
        raise ValueError(
            "Valid Apgar percentages should total 100; "
            f"found {percentage_total}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp")
    result.to_csv(temporary_path, index=False)
    temporary_path.replace(output_path)

    print(f"Created: {output_path}")
    print(f"Rows: {len(result)}")

    return result

def main() -> None:
    """Process all implemented newborn summary reports."""

    process_summary_report_8()
    process_summary_report_9()


if __name__ == "__main__":
    main()