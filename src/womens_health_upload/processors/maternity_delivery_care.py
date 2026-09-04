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

REPORT_6_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-care-summary-report-6.csv"
)

REPORT_7_OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-care-summary-report-7.csv"
)

REPORT_4_SHEET_NAME = "Summary report 4"
REPORT_5_SHEET_NAME = "Summary report 5"
REPORT_6_SHEET_NAME = "Summary report 6"
REPORT_7_SHEET_NAME = "Summary report 7"

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

SOURCE_TO_PUBLIC_DELIVERY_METHOD = {
    "Total": "All delivery methods",
    "Spontaneous": "Spontaneous",
    "Instrumental": "Instrumental",
    "Caesarean": "Caesarean",
}

POSTNATAL_STAY_CATEGORIES = [
    ("Same day", 0, 0),
    ("1 day", 1, 1),
    ("2 days", 2, 2),
    ("3 days", 3, 3),
    ("4 days", 4, 4),
    ("5 days", 5, 5),
    ("6 days", 6, 6),
    ("7 days or more", 7, 270),
]

EXPECTED_DELIVERY_COMPLICATIONS = [
    (
        "O70",
        "Perineal laceration during delivery",
    ),
    (
        "O36",
        "Maternal care for other known or suspected fetal problems",
    ),
    (
        "O99",
        (
            "Other maternal diseases classifiable elsewhere but "
            "complicating pregnancy, childbirth and the puerperium"
        ),
    ),
    (
        "O68",
        "Labour and delivery complicated by fetal stress [distress]",
    ),
    (
        "O72",
        "Postpartum haemorrhage",
    ),
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

def process_summary_report_6(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_6_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract the five (total) most prevalent delivery complications."""

    raw = read_source_sheet(
        source_path,
        REPORT_6_SHEET_NAME,
    )

    row_labels = (
        raw.iloc[:, 0]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    header_rows = raw.index[
        row_labels.eq("Complication (ICD-10 code)")
    ].tolist()

    if len(header_rows) != 1:
        raise ValueError(
            "Expected exactly one complication header row in "
            f"{REPORT_6_SHEET_NAME}; found {len(header_rows)}."
        )

    header_values = (
        raw.loc[header_rows[0]]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    description_columns = header_values.index[
        header_values.eq("Complication description")
    ].tolist()

    percentage_columns = header_values.index[
        header_values.eq("Percentage")
    ].tolist()

    if len(description_columns) != 1:
        raise ValueError(
            "Expected exactly one complication-description "
            f"column; found {len(description_columns)}."
        )

    if len(percentage_columns) != 1:
        raise ValueError(
            "Expected exactly one percentage column; "
            f"found {len(percentage_columns)}."
        )

    description_column = description_columns[0]
    percentage_column = percentage_columns[0]

    records: list[dict[str, object]] = []

    for source_order, (
        expected_code,
        expected_description,
    ) in enumerate(
        EXPECTED_DELIVERY_COMPLICATIONS,
        start=1,
    ):
        matching_rows = raw.index[
            row_labels.eq(expected_code)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected one row for ICD-10 code "
                f"{expected_code!r}; found {len(matching_rows)}."
            )

        source_row = matching_rows[0]

        observed_description = str(
            raw.at[source_row, description_column]
        ).strip()

        if observed_description != expected_description:
            raise ValueError(
                f"Description for {expected_code} differs "
                "from the expected ICD-10 description. "
                f"Found: {observed_description!r}"
            )

        percentage = pd.to_numeric(
            raw.at[source_row, percentage_column],
            errors="raise",
        )

        if pd.isna(percentage):
            raise ValueError(
                f"Missing percentage for {expected_code}."
            )

        if percentage < 0 or percentage > 100:
            raise ValueError(
                f"Percentage outside 0–100 for {expected_code}."
            )

        if percentage % 1 != 0:
            raise ValueError(
                "Expected a whole published percentage for "
                f"{expected_code}; found {percentage}."
            )

        records.append(
            {
                "reporting_period": "2024-25",
                "source_order": source_order,
                "complication_icd10_code": expected_code,
                "complication_description": (
                    expected_description
                ),
                "percentage_of_delivery_episodes": int(
                    percentage
                ),
                "denominator_scope": (
                    "All finished delivery episodes in England"
                ),
                "overlap_note": (
                    "A delivery episode may have no recorded "
                    "complication or more than one complication; "
                    "percentages must not be summed."
                ),
                "source_context_note": (
                    "Complications from earlier in pregnancy "
                    "may be recorded when relevant to care "
                    "during the delivery episode."
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
                "source_sheet": REPORT_6_SHEET_NAME,
            }
        )

    result = pd.DataFrame.from_records(records)

    if len(result) != 5:
        raise ValueError(
            "Expected five Report 6 output rows; "
            f"produced {len(result)}."
        )

    if result["complication_icd10_code"].duplicated().any():
        raise ValueError(
            "Duplicate ICD-10 complication codes were produced."
        )

    if not result[
        "percentage_of_delivery_episodes"
    ].is_monotonic_decreasing:
        raise ValueError(
            "Report 6 complication percentages are not in "
            "non-increasing prevalence order."
        )

    write_processed_csv(
        result,
        output_path,
    )

    return result

def process_summary_report_7(
    source_path: Path = SOURCE_FILE,
    output_path: Path = REPORT_7_OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract delivery-method distributions by postnatal stay."""

    raw = read_source_sheet(
        source_path,
        REPORT_7_SHEET_NAME,
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
            f"header row in {REPORT_7_SHEET_NAME}; "
            f"found {len(header_rows)}."
        )

    header_values = (
        raw.loc[header_rows[0]]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    stay_columns: dict[str, int] = {}

    for stay_category, _, _ in POSTNATAL_STAY_CATEGORIES:
        matching_columns = header_values.index[
            header_values.eq(stay_category)
        ].tolist()

        if len(matching_columns) != 1:
            raise ValueError(
                f"Expected one column for {stay_category!r}; "
                f"found {len(matching_columns)}."
            )

        stay_columns[stay_category] = matching_columns[0]

    values_by_method: dict[str, dict[str, int]] = {}

    for source_method in SOURCE_TO_PUBLIC_DELIVERY_METHOD:
        matching_rows = raw.index[
            row_labels.eq(source_method)
        ].tolist()

        if len(matching_rows) != 1:
            raise ValueError(
                f"Expected one row for {source_method!r}; "
                f"found {len(matching_rows)}."
            )

        values = pd.to_numeric(
            raw.loc[
                matching_rows[0],
                list(stay_columns.values()),
            ],
            errors="raise",
        )

        if values.isna().any():
            raise ValueError(
                f"Missing percentage for {source_method!r}."
            )

        if ((values < 0) | (values > 100)).any():
            raise ValueError(
                "Percentage outside 0–100 for "
                f"{source_method!r}."
            )

        if ((values % 1) != 0).any():
            raise ValueError(
                "Non-integer published percentage for "
                f"{source_method!r}."
            )

        integer_values = values.astype("int64").tolist()

        values_by_method[source_method] = dict(
            zip(
                stay_columns,
                integer_values,
                strict=True,
            )
        )

    records: list[dict[str, object]] = []

    for (
        source_method,
        public_method,
    ) in SOURCE_TO_PUBLIC_DELIVERY_METHOD.items():
        for stay_order, (
            stay_category,
            minimum_days,
            maximum_days,
        ) in enumerate(
            POSTNATAL_STAY_CATEGORIES,
            start=1,
        ):
            records.append(
                {
                    "reporting_period": "2024-25",
                    "delivery_method": public_method,
                    "source_delivery_method_label": (
                        source_method
                    ),
                    "postnatal_stay_category": (
                        stay_category
                    ),
                    "postnatal_stay_order": stay_order,
                    "minimum_days": minimum_days,
                    "maximum_days": maximum_days,
                    "percentage_within_delivery_method": (
                        values_by_method[source_method][
                            stay_category
                        ]
                    ),
                    "denominator_scope": (
                        "Deliveries with known method of "
                        "delivery and known postnatal-stay "
                        "duration"
                    ),
                    "postnatal_stay_definition": (
                        "Days between the first baby's birth "
                        "and the end of the finished delivery "
                        "episode"
                    ),
                    "unknown_duration_note": (
                        "Durations over 270 days or null are "
                        "classified as unknown and excluded"
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
                    "source_sheet": REPORT_7_SHEET_NAME,
                }
            )

    result = pd.DataFrame.from_records(records)

    if len(result) != 32:
        raise ValueError(
            "Expected 32 Report 7 output rows; "
            f"produced {len(result)}."
        )

    if result[
        [
            "reporting_period",
            "delivery_method",
            "postnatal_stay_category",
        ]
    ].duplicated().any():
        raise ValueError(
            "Duplicate delivery-method and stay-duration "
            "combinations were produced for Report 7."
        )

    counts_by_method = result.groupby(
        "delivery_method"
    ).size()

    if not counts_by_method.eq(8).all():
        raise ValueError(
            "Each Report 7 delivery method must contain "
            "eight postnatal-stay categories."
        )

    observed_categories = set(
        result["postnatal_stay_category"].unique()
    )

    expected_categories = {
        category
        for category, _, _ in POSTNATAL_STAY_CATEGORIES
    }

    if observed_categories != expected_categories:
        raise ValueError(
            "Report 7 stay categories differ from "
            "the expected set."
        )

    percentage_totals = result.groupby(
        "delivery_method",
        sort=False,
    )["percentage_within_delivery_method"].sum()

    invalid_totals = percentage_totals[
        ~percentage_totals.between(99, 101)
    ]

    if not invalid_totals.empty:
        raise ValueError(
            "Postnatal-stay percentages should total "
            "approximately 100 within each delivery method. "
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
    process_summary_report_6()
    process_summary_report_7()


if __name__ == "__main__":
    main()