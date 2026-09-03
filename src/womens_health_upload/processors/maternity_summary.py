"""Process tables from the NHS Maternity Statistics summary workbook."""

from pathlib import Path
import warnings

import pandas as pd


SOURCE_FILE = Path(
    "data/raw/nhs_maternity/"
    "hosp-epis-stat-mat-summary-tables-2425.xlsx"
)

OUTPUT_FILE = Path(
    "data/processed/nhs_maternity/"
    "nhs-maternity-delivery-trends-summary-report-1.csv"
)

SHEET_NAME = "Summary report 1"

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


def process_summary_report_1(
    source_path: Path = SOURCE_FILE,
    output_path: Path = OUTPUT_FILE,
) -> pd.DataFrame:
    """Extract and validate the national delivery-count time series."""

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Source workbook was not found: {source_path}"
        )

    # The warning concerns a decorative Excel header/footer, not the data.
    warnings.filterwarnings(
        "ignore",
        message="Cannot parse header or footer",
        category=UserWarning,
    )

    raw = pd.read_excel(
        source_path,
        sheet_name=SHEET_NAME,
        header=None,
    )

    # Locate the one row labelled "Total" instead of assuming that it will
    # always remain at a particular Excel row number.
    row_labels = raw.iloc[:, 0].fillna("").astype(str).str.strip()
    total_rows = raw.index[row_labels.eq("Total")].tolist()

    if len(total_rows) != 1:
        raise ValueError(
            f"Expected exactly one 'Total' row in {SHEET_NAME}; "
            f"found {len(total_rows)}."
        )

    total_row = total_rows[0]
    period_row = total_row - 1

    # Identify columns whose headings look like UK financial accounting years.
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
            "The reporting periods differ from the expected 2014-15 "
            f"to 2024-25 series. Found: {periods}"
        )

    counts = pd.to_numeric(
        raw.loc[total_row, period_columns],
        errors="raise",
    )

    if counts.isna().any():
        raise ValueError("One or more delivery counts are missing.")

    if (counts < 0).any():
        raise ValueError("Delivery counts cannot be negative.")

    if ((counts % 1) != 0).any():
        raise ValueError("Delivery counts must be whole numbers.")

    result = pd.DataFrame(
        {
            "reporting_period": periods,
            "number_of_deliveries": counts.astype("int64").tolist(),
            "geography": "England",
            "unit": "count",
            "source": "Hospital Episode Statistics (HES), NHS England",
            "source_release": "NHS Maternity Statistics, 2024-25",
            "source_file": source_path.name,
            "source_sheet": SHEET_NAME,
        }
    )

    if result["reporting_period"].duplicated().any():
        raise ValueError("Duplicate reporting periods were produced.")

    if len(result) != 11:
        raise ValueError(
            f"Expected 11 output rows; produced {len(result)}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file first, then replace the final output.
    # This prevents a failed run from leaving a partly written CSV.
    temporary_path = output_path.with_suffix(".tmp")
    result.to_csv(temporary_path, index=False)
    temporary_path.replace(output_path)

    print(f"Created: {output_path}")
    print(f"Rows: {len(result)}")
    print(result.to_string(index=False))

    return result


if __name__ == "__main__":
    process_summary_report_1()