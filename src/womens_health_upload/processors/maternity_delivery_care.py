"""Process NHS Maternity Statistics delivery-care summary tables."""

import warnings
from pathlib import Path

import pandas as pd

SOURCE_FILE = Path(
    "data/raw/nhs_maternity/"
    "hosp-epis-stat-mat-summary-tables-2425.xlsx"
)

REPORT_4_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-care-summary-report-4.csv"
)

REPORT_5_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-care-summary-report-5.csv"
)

REPORT_4_SHEET_NAME = "Summary report 4"
REPORT_5_SHEET_NAME = "Summary report 5"

EXPECTED_PERIODS = [
    "2014-15",
    "2024-25",
]

SOURCE_TO_PUBLIC_AGE_GROUP = {
    "Total deliveries": "All age groups",
    "Under 20 years": "Under 20 years",
    "20-29 years": "20-29 years",
    "30-39 years": "30-39 years",
    "40 years and over": "40 years and over",
}

EXPECTED_METHODS_OF_DELIVERY = [
    "Spontaneous",
    "Instrumental",
    "Caesarean",
]

def read_source_sheet(
    source_path: Path,
    sheet_name: str,
) -> pd.DataFrame:
    """Read one source worksheet without altering the workbook."""

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
    """Find and validate the Report 4 period columns."""

    possible_periods = (
        raw.loc[period_row]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    period_columns = possible_periods.index[
        possible_periods.str.fullmatch(r"\d{4}-\d{2}")
    ].tolist()

    periods = possible_periods.loc[
        period_columns
    ].tolist()

    if periods != EXPECTED_PERIODS:
        raise ValueError(
            "Report 4 periods differ from the expected "
            f"2014-15 and 2024-25 values. Found: {periods}"
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


def process_summary_report_4(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_4_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract anaesthetic or analgesic use by age group."""

    raw = read_source_sheet(
        source_path,
        REPORT_4_SHEET_NAME,
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
            f"{REPORT_4_SHEET_NAME}; found {len(header_rows)}."
        )

    period_columns, periods = find_reporting_periods(
        raw,
        header_rows[0],
    )

    values_by_source_group: dict[str, list[int]] = {}

    for source_age_group in SOURCE_TO_PUBLIC_AGE_GROUP:
        matching_rows = raw.index[
            row_labels.eq(source_age_group)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected one row for {source_age_group!r}; "
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
                f"Missing percentage for {source_age_group!r}."
            )

        if ((values < 0) | (values > 100)).any():
            raise ValueError(
                "Percentage outside 0–100 for "
                f"{source_age_group!r}."
            )

        if ((values % 1) != 0).any():
            raise ValueError(
                "Non-integer published percentage for "
                f"{source_age_group!r}."
            )

        values_by_source_group[source_age_group] = (
            values.astype("int64").tolist()
        )

    records: list[dict[str, object]] = []

    for period_position, period in enumerate(periods):
        for (
            source_age_group,
            public_age_group,
        ) in SOURCE_TO_PUBLIC_AGE_GROUP.items():
            data_note = ""

            if period == "2024-25":
                data_note = (
                    "Includes 'other'; excludes n/a values."
                )

            records.append(
                {
                    "reporting_period": period,
                    "age_group": public_age_group,
                    "source_age_group_label": (
                        source_age_group
                    ),
                    "percentage_with_anaesthetic_or_analgesic": (
                        values_by_source_group[
                            source_age_group
                        ][period_position]
                    ),
                    "data_note": data_note,
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
                    "source_sheet": REPORT_4_SHEET_NAME,
                }
            )

    result = pd.DataFrame.from_records(records)

    if len(result) != 10:
        raise ValueError(
            "Expected 10 Report 4 output rows; "
            f"produced {len(result)}."
        )

    if result[
        ["reporting_period", "age_group"]
    ].duplicated().any():
        raise ValueError(
            "Duplicate period and age-group combinations "
            "were produced for Report 4."
        )

    counts_by_period = result.groupby(
        "reporting_period"
    ).size()

    if not counts_by_period.eq(5).all():
        raise ValueError(
            "Each Report 4 period must contain five "
            "age-group rows."
        )

    observed_groups = set(
        result["age_group"].unique()
    )

    expected_groups = set(
        SOURCE_TO_PUBLIC_AGE_GROUP.values()
    )

    if observed_groups != expected_groups:
        raise ValueError(
            "Report 4 age groups differ from the expected set."
        )

    notes_2024 = result.loc[
        result["reporting_period"] == "2024-25",
        "data_note",
    ]

    if (
        len(notes_2024) != 5
        or not notes_2024.str.contains(
            "excludes n/a",
            regex=False,
        ).all()
    ):
        raise ValueError(
            "The 2024-25 denominator note was not preserved."
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result

def process_summary_report_5(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_5_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract delivery-method percentages by maternal age group."""

    raw = read_source_sheet(
        source_path,
        REPORT_5_SHEET_NAME,
    )

    row_labels = (
        raw.iloc[:, 0]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    header_rows = raw.index[
        row_labels.eq("Method of delivery")
    ].tolist()

    if len(header_rows) != 1:
        raise ValueError(
            "Expected exactly one 'Method of delivery' "
            f"header row in {REPORT_5_SHEET_NAME}; "
            f"found {len(header_rows)}."
        )

    header_row = header_rows[0]

    age_headers = (
        raw.loc[header_row]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    age_columns: dict[str, int] = {}

    for source_age_group in SOURCE_TO_PUBLIC_AGE_GROUP:
        matching_columns = age_headers.index[
            age_headers.eq(source_age_group)
        ].tolist()

        if len(matching_columns) != 1:
            raise ValueError(
                f"Expected one column for {source_age_group!r}; "
                f"found {len(matching_columns)}."
            )

        age_columns[source_age_group] = matching_columns[0]

    values_by_method: dict[str, dict[str, int]] = {}

    for method in EXPECTED_METHODS_OF_DELIVERY:
        matching_rows = raw.index[
            row_labels.eq(method)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected one row for {method!r}; "
                f"found {len(matching_rows)}."
            )

        values = pd.to_numeric(
            raw.loc[
                matching_rows[0],
                list(age_columns.values()),
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
                "Non-integer published percentage for "
                f"{method!r}."
            )

        integer_values = values.astype("int64").tolist()

        values_by_method[method] = dict(
            zip(
                age_columns,
                integer_values,
                strict=True,
            )
        )

    records: list[dict[str, object]] = []

    for (
        source_age_group,
        public_age_group,
    ) in SOURCE_TO_PUBLIC_AGE_GROUP.items():
        for method in EXPECTED_METHODS_OF_DELIVERY:
            records.append(
                {
                    "reporting_period": "2024-25",
                    "age_group": public_age_group,
                    "source_age_group_label": source_age_group,
                    "method_of_delivery": method,
                    "percentage_of_known_deliveries": (
                        values_by_method[method][source_age_group]
                    ),
                    "denominator_scope": (
                        "Deliveries with known method of delivery"
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
                    "source_sheet": REPORT_5_SHEET_NAME,
                }
            )

    result = pd.DataFrame.from_records(records)

    if len(result) != 15:
        raise ValueError(
            "Expected 15 Report 5 output rows; "
            f"produced {len(result)}."
        )

    if result[
        ["reporting_period", "age_group", "method_of_delivery"]
    ].duplicated().any():
        raise ValueError(
            "Duplicate age-group and delivery-method "
            "combinations were produced for Report 5."
        )

    counts_by_age_group = result.groupby(
        "age_group"
    ).size()

    if not counts_by_age_group.eq(3).all():
        raise ValueError(
            "Each Report 5 age group must contain "
            "three delivery methods."
        )

    observed_methods = set(
        result["method_of_delivery"].unique()
    )

    if observed_methods != set(
        EXPECTED_METHODS_OF_DELIVERY
    ):
        raise ValueError(
            "Report 5 delivery methods differ from "
            "the expected set."
        )

    percentage_totals = result.groupby(
        "age_group",
        sort=False,
    )["percentage_of_known_deliveries"].sum()

    invalid_totals = percentage_totals[
        ~percentage_totals.between(99, 101)
    ]

    if not invalid_totals.empty:
        raise ValueError(
            "Delivery-method percentages should total "
            "approximately 100 for each age group. "
            f"Invalid totals: {invalid_totals.to_dict()}"
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result

def main() -> None:
    """Process all implemented delivery-care reports."""

    process_summary_report_4()
    process_summary_report_5()


if __name__ == "__main__":
    main()