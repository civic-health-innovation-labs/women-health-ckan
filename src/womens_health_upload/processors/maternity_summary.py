"""Process tables from the NHS Maternity Statistics summary workbook."""

import warnings
from pathlib import Path

import pandas as pd

SOURCE_FILE = Path(
    "data/raw/nhs_maternity/"
    "hosp-epis-stat-mat-summary-tables-2425.xlsx"
)

REPORT_1_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-trends-summary-report-1.csv"
)

REPORT_2_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-trends-summary-report-2.csv"
)

REPORT_3_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-trends-summary-report-3.csv"
)

REPORT_1_SHEET_NAME = "Summary report 1"
REPORT_2_SHEET_NAME = "Summary report 2"
REPORT_3_SHEET_NAME = "Summary report 3"

EXPECTED_PERIODS = [
    "2014-15",
    "2015-16",
    "2016-17",
    "2017-18",
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
]

EXPECTED_AGE_GROUPS = [
    "All Age Groups",
    "Under 20 years",
    "20-29 years",
    "30-39 years",
    "40+ years",
]

EXPECTED_METHODS_OF_ONSET = [
    "Caesarean",
    "Spontaneous",
    "Induced",
]

def read_source_sheet(
    source_path: Path,
    sheet_name: str,
) -> pd.DataFrame:
    """Read one worksheet while suppressing a decorative-header warning."""

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Source workbook was not found: {source_path}"
        )

    warnings.filterwarnings(
        "ignore",
        message="Cannot parse header or footer",
        category=UserWarning,
    )

    return pd.read_excel(
        source_path,
        sheet_name=sheet_name,
        header=None,
    )


def find_reporting_periods(
    raw: pd.DataFrame,
    period_row: int,
) -> tuple[list[int], list[str]]:
    """Find and validate the expected financial-year columns."""

    possible_periods = (
        raw.loc[period_row]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    period_columns = possible_periods.index[
        possible_periods.str.fullmatch(r"\d{4}-\d{2}")
    ].tolist()

    periods = possible_periods.loc[period_columns].tolist()

    if periods != EXPECTED_PERIODS:
        raise ValueError(
            "The reporting periods differ from the expected "
            f"2014-15 to 2024-25 series. Found: {periods}"
        )

    return period_columns, periods


def write_processed_csv(
    result: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write a processed CSV atomically."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = output_path.with_suffix(".tmp")
    result.to_csv(temporary_path, index=False)
    temporary_path.replace(output_path)

    print(f"Created: {output_path}")
    print(f"Rows: {len(result)}")


def process_summary_report_1(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_1_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract and validate the national delivery-count time series."""

    raw = read_source_sheet(
        source_path,
        REPORT_1_SHEET_NAME,
    )

    row_labels = (
        raw.iloc[:, 0]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    total_rows = raw.index[
        row_labels.eq("Total")
    ].tolist()

    if len(total_rows) != 1:
        raise ValueError(
            "Expected exactly one 'Total' row in "
            f"{REPORT_1_SHEET_NAME}; found {len(total_rows)}."
        )

    total_row = total_rows[0]
    period_row = total_row - 1

    period_columns, periods = find_reporting_periods(
        raw,
        period_row,
    )

    counts = pd.to_numeric(
        raw.loc[total_row, period_columns],
        errors="raise",
    )

    if counts.isna().any():
        raise ValueError(
            "One or more delivery counts are missing."
        )

    if (counts < 0).any():
        raise ValueError(
            "Delivery counts cannot be negative."
        )

    if ((counts % 1) != 0).any():
        raise ValueError(
            "Delivery counts must be whole numbers."
        )

    result = pd.DataFrame(
        {
            "reporting_period": periods,
            "number_of_deliveries": (
                counts.astype("int64").tolist()
            ),
            "geography": "England",
            "unit": "count",
            "source": (
                "Hospital Episode Statistics (HES), "
                "NHS England"
            ),
            "source_release": (
                "NHS Maternity Statistics, 2024-25"
            ),
            "source_file": source_path.name,
            "source_sheet": REPORT_1_SHEET_NAME,
        }
    )

    if result["reporting_period"].duplicated().any():
        raise ValueError(
            "Duplicate reporting periods were produced "
            "for Summary Report 1."
        )

    if len(result) != 11:
        raise ValueError(
            "Expected 11 Report 1 output rows; "
            f"produced {len(result)}."
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result


def process_summary_report_2(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_2_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract delivery-number indices by maternal age group."""

    raw = read_source_sheet(
        source_path,
        REPORT_2_SHEET_NAME,
    )

    row_labels = (
        raw.iloc[:, 0]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    header_rows = raw.index[
        row_labels.eq("Age Group")
    ].tolist()

    if len(header_rows) != 1:
        raise ValueError(
            "Expected exactly one 'Age Group' header row in "
            f"{REPORT_2_SHEET_NAME}; found {len(header_rows)}."
        )

    period_row = header_rows[0]

    period_columns, periods = find_reporting_periods(
        raw,
        period_row,
    )

    values_by_age_group: dict[str, list[int]] = {}

    for age_group in EXPECTED_AGE_GROUPS:
        matching_rows = raw.index[
            row_labels.eq(age_group)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected exactly one row for {age_group!r}; "
                f"found {len(matching_rows)}."
            )

        values = pd.to_numeric(
            raw.loc[
                matching_rows[0],
                period_columns,
            ],
            errors="raise",
        )

        if values.isna().any():
            raise ValueError(
                f"Missing index value for {age_group!r}."
            )

        if (values < 0).any():
            raise ValueError(
                f"Negative index value for {age_group!r}."
            )

        if ((values % 1) != 0).any():
            raise ValueError(
                f"Non-integer index value for {age_group!r}."
            )

        values_by_age_group[age_group] = (
            values.astype("int64").tolist()
        )

    records: list[dict[str, object]] = []

    for period_position, period in enumerate(periods):
        for age_group in EXPECTED_AGE_GROUPS:
            records.append(
                {
                    "reporting_period": period,
                    "age_group": age_group,
                    "delivery_index": (
                        values_by_age_group[age_group][
                            period_position
                        ]
                    ),
                    "index_base_period": "2014-15",
                    "index_base_value": 100,
                    "geography": "England",
                    "unit": "index",
                    "source": (
                        "Hospital Episode Statistics (HES), "
                        "NHS England"
                    ),
                    "source_release": (
                        "NHS Maternity Statistics, 2024-25"
                    ),
                    "source_file": source_path.name,
                    "source_sheet": REPORT_2_SHEET_NAME,
                }
            )

    result = pd.DataFrame.from_records(records)

    if len(result) != 55:
        raise ValueError(
            "Expected 55 Report 2 output rows; "
            f"produced {len(result)}."
        )

    if result[
        ["reporting_period", "age_group"]
    ].duplicated().any():
        raise ValueError(
            "Duplicate period and age-group combinations "
            "were produced for Summary Report 2."
        )

    baseline = result[
        result["reporting_period"] == "2014-15"
    ]

    if (
        len(baseline) != len(EXPECTED_AGE_GROUPS)
        or not baseline["delivery_index"].eq(100).all()
    ):
        raise ValueError(
            "Every age group must have a 2014-15 baseline "
            "index value of 100."
        )

    observed_age_groups = set(
        result["age_group"].unique()
    )

    if observed_age_groups != set(EXPECTED_AGE_GROUPS):
        raise ValueError(
            "Report 2 age groups differ from the expected set."
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result

def process_summary_report_3(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_3_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract percentages of known deliveries by method of onset."""

    raw = read_source_sheet(
        source_path,
        REPORT_3_SHEET_NAME,
    )

    row_labels = (
        raw.iloc[:, 0]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    header_rows = raw.index[
        row_labels.eq("Method of Onset")
    ].tolist()

    if len(header_rows) != 1:
        raise ValueError(
            "Expected exactly one 'Method of Onset' header "
            f"row in {REPORT_3_SHEET_NAME}; "
            f"found {len(header_rows)}."
        )

    period_row = header_rows[0]

    period_columns, periods = find_reporting_periods(
        raw,
        period_row,
    )

    values_by_method: dict[str, list[int]] = {}

    for method in EXPECTED_METHODS_OF_ONSET:
        matching_rows = raw.index[
            row_labels.eq(method)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected exactly one row for {method!r}; "
                f"found {len(matching_rows)}."
            )

        values = pd.to_numeric(
            raw.loc[
                matching_rows[0],
                period_columns,
            ],
            errors="raise",
        )

        if values.isna().any():
            raise ValueError(
                f"Missing percentage for {method!r}."
            )

        if ((values < 0) | (values > 100)).any():
            raise ValueError(
                f"Percentage outside 0–100 for {method!r}."
            )

        if ((values % 1) != 0).any():
            raise ValueError(
                f"Non-integer published percentage for {method!r}."
            )

        values_by_method[method] = (
            values.astype("int64").tolist()
        )

    records: list[dict[str, object]] = []

    for period_position, period in enumerate(periods):
        for method in EXPECTED_METHODS_OF_ONSET:
            records.append(
                {
                    "reporting_period": period,
                    "method_of_onset": method,
                    "percentage_of_known_deliveries": (
                        values_by_method[method][
                            period_position
                        ]
                    ),
                    "denominator_scope": (
                        "Deliveries with known method of onset"
                    ),
                    "geography": "England",
                    "unit": "percent",
                    "source": (
                        "Hospital Episode Statistics (HES), "
                        "NHS England"
                    ),
                    "source_release": (
                        "NHS Maternity Statistics, 2024-25"
                    ),
                    "source_file": source_path.name,
                    "source_sheet": REPORT_3_SHEET_NAME,
                }
            )

    result = pd.DataFrame.from_records(records)

    if len(result) != 33:
        raise ValueError(
            "Expected 33 Report 3 output rows; "
            f"produced {len(result)}."
        )

    if result[
        ["reporting_period", "method_of_onset"]
    ].duplicated().any():
        raise ValueError(
            "Duplicate period and method-of-onset "
            "combinations were produced."
        )

    observed_methods = set(
        result["method_of_onset"].unique()
    )

    if observed_methods != set(EXPECTED_METHODS_OF_ONSET):
        raise ValueError(
            "Report 3 methods differ from the expected set."
        )

    percentage_totals = result.groupby(
        "reporting_period",
        sort=False,
    )["percentage_of_known_deliveries"].sum()

    invalid_totals = percentage_totals[
        ~percentage_totals.between(99, 101)
    ]

    if not invalid_totals.empty:
        raise ValueError(
            "Method-of-onset percentages should total "
            "approximately 100 after rounding. Invalid totals: "
            f"{invalid_totals.to_dict()}"
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result

def main() -> None:
    """Process all implemented maternity summary reports."""

    process_summary_report_1()
    process_summary_report_2()
    process_summary_report_3()


if __name__ == "__main__":
    main()