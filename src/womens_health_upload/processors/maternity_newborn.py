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

def main() -> None:
    """Process all implemented newborn summary reports."""

    process_summary_report_8()


if __name__ == "__main__":
    main()