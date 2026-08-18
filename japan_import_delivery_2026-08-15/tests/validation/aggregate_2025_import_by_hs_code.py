"""Aggregate the 2025 country-level import CSV to one row per HS code."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "reference" / "2025" / "official_import_2025.csv"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "reference" / "2025" / "import_totals_by_hs_code.csv"
)
DIMENSION_COLUMNS = ("Exp or Imp", "Year", "HS", "Country", "Unit1", "Unit2")


def normalize_hs_code(raw_value: str | None, row_number: int) -> str:
    """Return a normalized nine-digit HS code or raise a descriptive error."""
    value = (raw_value or "").strip().strip("'\"").strip()
    if len(value) != 9 or not value.isdigit():
        raise ValueError(
            f"Invalid HS code at CSV row {row_number}: {raw_value!r}. "
            "Expected exactly nine digits."
        )
    return value


def parse_integer(raw_value: str | None, column: str, row_number: int) -> int:
    """Parse an integer data cell, treating a blank cell as zero."""
    value = (raw_value or "").strip().replace(",", "")
    if not value:
        return 0
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(
            f"Invalid integer at CSV row {row_number}, column {column!r}: {raw_value!r}"
        ) from error


def get_numeric_columns(fieldnames: Iterable[str]) -> list[str]:
    """Return the annual and monthly quantity/value columns in source order."""
    return [
        column
        for column in fieldnames
        if column.startswith(("Quantity1-", "Quantity2-", "Value-"))
    ]


def aggregate_rows(
    reader: csv.DictReader,
    numeric_columns: list[str],
) -> list[dict[str, str]]:
    """Aggregate country rows and return one source-shaped row per HS code."""
    totals: dict[str, dict[str, str]] = {}

    for row_number, row in enumerate(reader, start=2):
        hs_code = normalize_hs_code(row.get("HS"), row_number)
        if hs_code not in totals:
            aggregate = dict(row)
            aggregate["Country"] = ""
            for column in numeric_columns:
                aggregate[column] = "0"
            totals[hs_code] = aggregate
        else:
            aggregate = totals[hs_code]
            for column in ("Exp or Imp", "Year", "Unit1", "Unit2"):
                if row.get(column, "").strip() != aggregate.get(column, "").strip():
                    raise ValueError(
                        f"Inconsistent {column!r} for HS code {hs_code} "
                        f"at CSV row {row_number}."
                    )

        for column in numeric_columns:
            current_total = int(aggregate[column])
            aggregate[column] = str(
                current_total + parse_integer(row.get(column), column, row_number)
            )

    return [totals[hs_code] for hs_code in sorted(totals)]


def aggregate_csv(input_path: Path, output_path: Path) -> int:
    """Aggregate an input CSV while preserving its headers and column order."""
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"Input CSV does not contain a header row: {input_path}")

        missing_columns = [
            column for column in DIMENSION_COLUMNS if column not in reader.fieldnames
        ]
        if missing_columns:
            raise ValueError(
                f"Input CSV is missing required columns: {', '.join(missing_columns)}"
            )

        numeric_columns = get_numeric_columns(reader.fieldnames)
        if not numeric_columns:
            raise ValueError("Input CSV does not contain quantity or value columns.")

        rows = aggregate_rows(reader, numeric_columns)
        fieldnames = reader.fieldnames

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sum the 2025 import country rows into one row per HS code."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Source CSV (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if input_path == output_path:
        raise ValueError("Input and output paths must be different.")

    row_count = aggregate_csv(input_path, output_path)
    print(f"Wrote {row_count} HS-code totals to {output_path}")


if __name__ == "__main__":
    main()
