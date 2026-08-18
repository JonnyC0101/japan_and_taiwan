"""Compare fetched monthly import data with the aggregated 2025 reference CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FETCHED = PROJECT_ROOT / "data" / "raw" / "import_2025.csv"
DEFAULT_REFERENCE = (
    PROJECT_ROOT / "data" / "reference" / "2025" / "import_totals_by_hs_code.csv"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "validation_2025.csv"
MONTH_COLUMNS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
OUTPUT_COLUMNS = (
    "month",
    "hs_code",
    "reference_unit1",
    "fetched_unit1",
    "reference_quantity1",
    "fetched_quantity1",
    "quantity1_difference",
    "reference_unit2",
    "fetched_unit2",
    "reference_quantity2",
    "fetched_quantity2",
    "quantity2_difference",
    "reference_value_thousand_yen",
    "fetched_value_thousand_yen",
    "value_difference_thousand_yen",
    "status",
    "notes",
)


class ValidationError(RuntimeError):
    """Raised when input files are incomplete or structurally unsafe to compare."""


def normalize_hs_code(raw_value: str | None, context: str) -> str:
    value = (raw_value or "").strip().strip("'\"").strip()
    if len(value) != 9 or not value.isdigit():
        raise ValidationError(
            f"Invalid HS code in {context}: {raw_value!r}. Expected nine digits."
        )
    return value


def parse_integer(
    raw_value: str | None,
    context: str,
    *,
    blank_as_zero: bool,
) -> int | None:
    value = (raw_value or "").strip().replace(",", "")
    if not value:
        return 0 if blank_as_zero else None
    try:
        return int(value)
    except ValueError as error:
        raise ValidationError(f"Invalid integer in {context}: {raw_value!r}") from error


def normalize_unit(raw_value: str | None) -> str:
    return (raw_value or "").strip().upper()


def require_columns(
    fieldnames: list[str] | None,
    required: Iterable[str],
    path: Path,
) -> None:
    if fieldnames is None:
        raise ValidationError(f"CSV does not contain a header row: {path}")
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise ValidationError(
            f"CSV is missing required columns in {path}: {', '.join(missing)}"
        )


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValidationError(
            f"Fetch manifest not found: {path}. The manifest is required so an "
            "incomplete fetch cannot be mistaken for zero trade."
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"Could not read fetch manifest: {path}") from error
    if manifest.get("status") != "complete":
        raise ValidationError(f"Fetch manifest is not marked complete: {path}")
    if manifest.get("direction") != "import":
        raise ValidationError("This validator expects an import fetch manifest.")
    months = manifest.get("months")
    if not isinstance(months, dict) or not months:
        raise ValidationError("Fetch manifest does not contain completed months.")
    return manifest


def load_fetched(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        require_columns(
            reader.fieldnames,
            (
                "direction",
                "month",
                "hs_code",
                "unit1",
                "quantity1",
                "unit2",
                "quantity2",
                "value_thousand_yen",
            ),
            path,
        )
        for row_number, row in enumerate(reader, start=2):
            if row["direction"].strip().lower() != "import":
                raise ValidationError(
                    f"Expected import at row {row_number} of {path}."
                )
            month = row["month"].strip()
            validate_month(month, f"row {row_number} of {path}")
            hs_code = normalize_hs_code(
                row["hs_code"], f"row {row_number} of {path}"
            )
            key = (month, hs_code)
            if key in rows:
                raise ValidationError(
                    f"Duplicate fetched row for {month}, HS {hs_code}."
                )
            rows[key] = {
                "unit1": normalize_unit(row["unit1"]),
                "quantity1": parse_integer(
                    row["quantity1"],
                    f"quantity1 at row {row_number} of {path}",
                    blank_as_zero=True,
                ),
                "unit2": normalize_unit(row["unit2"]),
                "quantity2": parse_integer(
                    row["quantity2"],
                    f"quantity2 at row {row_number} of {path}",
                    blank_as_zero=True,
                ),
                "value": parse_integer(
                    row["value_thousand_yen"],
                    f"value at row {row_number} of {path}",
                    blank_as_zero=True,
                ),
            }
    return rows


def load_reference(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = ["Exp or Imp", "Year", "HS", "Unit1", "Unit2"]
        for suffix in MONTH_COLUMNS.values():
            required.extend(
                (f"Quantity1-{suffix}", f"Quantity2-{suffix}", f"Value-{suffix}")
            )
        require_columns(reader.fieldnames, required, path)
        for row_number, row in enumerate(reader, start=2):
            if row["Exp or Imp"].strip() != "2":
                raise ValidationError(
                    f"Expected import code 2 at row {row_number} of {path}."
                )
            if row["Year"].strip() != "2025":
                raise ValidationError(
                    f"Expected year 2025 at row {row_number} of {path}."
                )
            hs_code = normalize_hs_code(row["HS"], f"row {row_number} of {path}")
            if hs_code in rows:
                raise ValidationError(f"Duplicate reference HS code: {hs_code}")
            rows[hs_code] = row
    if not rows:
        raise ValidationError(f"Reference CSV is empty: {path}")
    return rows


def validate_month(value: str, context: str) -> tuple[int, int]:
    parts = value.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValidationError(f"Invalid month in {context}: {value!r}")
    year, month = int(parts[0]), int(parts[1])
    if year != 2025 or month not in MONTH_COLUMNS:
        raise ValidationError(
            f"This validator only accepts months in 2025; got {value!r} in {context}."
        )
    if value != f"{year:04d}-{month:02d}":
        raise ValidationError(f"Month must use YYYY-MM format in {context}: {value!r}")
    return year, month


def reference_values(row: dict[str, str], month: str) -> dict[str, Any]:
    _, month_number = validate_month(month, "reference comparison")
    suffix = MONTH_COLUMNS[month_number]
    hs_code = normalize_hs_code(row["HS"], "reference row")
    return {
        "unit1": normalize_unit(row["Unit1"]),
        "quantity1": parse_integer(
            row[f"Quantity1-{suffix}"],
            f"reference Quantity1 for {hs_code}, {month}",
            blank_as_zero=True,
        ),
        "unit2": normalize_unit(row["Unit2"]),
        "quantity2": parse_integer(
            row[f"Quantity2-{suffix}"],
            f"reference Quantity2 for {hs_code}, {month}",
            blank_as_zero=True,
        ),
        "value": parse_integer(
            row[f"Value-{suffix}"],
            f"reference Value for {hs_code}, {month}",
            blank_as_zero=True,
        ),
    }


def verify_manifest_coverage(
    manifest: dict[str, Any],
    fetched: dict[tuple[str, str], dict[str, Any]],
    reference_codes: set[str],
) -> list[str]:
    months = sorted(manifest["months"])
    for month in months:
        validate_month(month, "fetch manifest")
        month_info = manifest["months"][month]
        if not isinstance(month_info, dict):
            raise ValidationError(f"Invalid manifest entry for {month}.")
        missing_raw = month_info.get("missing_hs_codes")
        if not isinstance(missing_raw, list):
            raise ValidationError(f"Manifest is missing the HS absence list for {month}.")
        missing = {
            normalize_hs_code(code, f"manifest month {month}") for code in missing_raw
        }
        returned = {hs for row_month, hs in fetched if row_month == month}
        if returned & missing:
            raise ValidationError(
                f"Manifest marks returned HS codes as missing for {month}."
            )
        if returned | missing != reference_codes:
            absent = sorted(reference_codes - returned - missing)
            unexpected = sorted((returned | missing) - reference_codes)
            raise ValidationError(
                f"Manifest coverage does not match the reference HS list for {month}. "
                f"Unaccounted: {absent[:5]}; unexpected: {unexpected[:5]}."
            )
        declared_returned = month_info.get("returned_hs_count")
        if declared_returned != len(returned):
            raise ValidationError(
                f"Manifest says {declared_returned} HS codes returned for {month}, "
                f"but CSV contains {len(returned)}."
            )
    fetched_months = {month for month, _ in fetched}
    if fetched_months - set(months):
        raise ValidationError(
            f"Fetched CSV contains months absent from manifest: "
            f"{sorted(fetched_months - set(months))}"
        )
    if manifest.get("written_row_count") != len(fetched):
        raise ValidationError(
            f"Manifest says {manifest.get('written_row_count')} rows were written, "
            f"but fetched CSV contains {len(fetched)}."
        )
    return months


def compare_data(
    fetched: dict[tuple[str, str], dict[str, Any]],
    reference: dict[str, dict[str, str]],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    months = verify_manifest_coverage(manifest, fetched, set(reference))
    output_rows: list[dict[str, Any]] = []

    for month in months:
        for hs_code in sorted(reference):
            reference_row = reference_values(reference[hs_code], month)
            fetched_row = fetched.get((month, hs_code))
            base: dict[str, Any] = {
                "month": month,
                "hs_code": f"'{hs_code}",
                "reference_unit1": reference_row["unit1"],
                "fetched_unit1": "",
                "reference_quantity1": reference_row["quantity1"],
                "fetched_quantity1": "",
                "quantity1_difference": "",
                "reference_unit2": reference_row["unit2"],
                "fetched_unit2": "",
                "reference_quantity2": reference_row["quantity2"],
                "fetched_quantity2": "",
                "quantity2_difference": "",
                "reference_value_thousand_yen": reference_row["value"],
                "fetched_value_thousand_yen": "",
                "value_difference_thousand_yen": "",
                "status": "",
                "notes": "",
            }
            if fetched_row is None:
                reference_is_zero = all(
                    reference_row[field] == 0
                    for field in ("quantity1", "quantity2", "value")
                )
                if reference_is_zero:
                    base["status"] = "PASS_ZERO_NOT_RETURNED"
                    base["notes"] = "Customs page omitted a confirmed all-zero month."
                else:
                    base["status"] = "FAIL_MISSING_FETCHED"
                    base["notes"] = "Reference has data but the fetched page returned no row."
                output_rows.append(base)
                continue

            base.update(
                {
                    "fetched_unit1": fetched_row["unit1"],
                    "fetched_quantity1": fetched_row["quantity1"],
                    "quantity1_difference": (
                        fetched_row["quantity1"] - reference_row["quantity1"]
                    ),
                    "fetched_unit2": fetched_row["unit2"],
                    "fetched_quantity2": fetched_row["quantity2"],
                    "quantity2_difference": (
                        fetched_row["quantity2"] - reference_row["quantity2"]
                    ),
                    "fetched_value_thousand_yen": fetched_row["value"],
                    "value_difference_thousand_yen": (
                        fetched_row["value"] - reference_row["value"]
                    ),
                }
            )
            differences: list[str] = []
            if fetched_row["unit1"] != reference_row["unit1"]:
                differences.append("Unit1")
            if fetched_row["quantity1"] != reference_row["quantity1"]:
                differences.append("Quantity1")
            if fetched_row["unit2"] != reference_row["unit2"]:
                differences.append("Unit2")
            if fetched_row["quantity2"] != reference_row["quantity2"]:
                differences.append("Quantity2")
            if fetched_row["value"] != reference_row["value"]:
                differences.append("Value")
            if differences:
                base["status"] = "FAIL_MISMATCH"
                base["notes"] = "Different fields: " + ", ".join(differences)
            else:
                base["status"] = "PASS"
            output_rows.append(base)

    statuses = Counter(row["status"] for row in output_rows)
    fail_count = sum(
        count for status, count in statuses.items() if status.startswith("FAIL")
    )
    numeric_rows = [
        row for row in output_rows if row["quantity1_difference"] != ""
    ]
    summary: dict[str, Any] = {
        "status": "PASS" if fail_count == 0 else "FAIL",
        "months_compared": months,
        "reference_hs_count": len(reference),
        "comparison_row_count": len(output_rows),
        "pass_count": len(output_rows) - fail_count,
        "fail_count": fail_count,
        "status_counts": dict(sorted(statuses.items())),
        "max_abs_quantity1_difference": max(
            (abs(row["quantity1_difference"]) for row in numeric_rows), default=0
        ),
        "max_abs_quantity2_difference": max(
            (abs(row["quantity2_difference"]) for row in numeric_rows), default=0
        ),
        "max_abs_value_difference_thousand_yen": max(
            (abs(row["value_difference_thousand_yen"]) for row in numeric_rows),
            default=0,
        ),
    }
    return output_rows, summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(
                destination, fieldnames=OUTPUT_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_files(
    fetched_path: Path,
    reference_path: Path,
    manifest_path: Path,
    output_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    fetched = load_fetched(fetched_path)
    reference = load_reference(reference_path)
    rows, summary = compare_data(fetched, reference, manifest)
    summary.update(
        {
            "fetched_file": str(fetched_path),
            "reference_file": str(reference_path),
            "manifest_file": str(manifest_path),
            "comparison_file": str(output_path),
        }
    )
    write_csv(output_path, rows)
    write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare fetched 2025 import rows with country-summed official data."
        )
    )
    parser.add_argument("--fetched", type=Path, default=DEFAULT_FETCHED)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Fetch manifest (default: same basename as --fetched).",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--summary",
        type=Path,
        help="Summary JSON (default: same basename as --output).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fetched_path = args.fetched.resolve()
    reference_path = args.reference.resolve()
    manifest_path = (
        args.manifest.resolve()
        if args.manifest
        else fetched_path.with_suffix(".manifest.json")
    )
    output_path = args.output.resolve()
    summary_path = (
        args.summary.resolve()
        if args.summary
        else output_path.with_suffix(".summary.json")
    )
    if output_path == summary_path:
        raise ValidationError("Comparison CSV and summary JSON paths must differ.")

    summary = validate_files(
        fetched_path,
        reference_path,
        manifest_path,
        output_path,
        summary_path,
    )
    print(f"Validation status: {summary['status']}")
    print(
        f"Compared {summary['comparison_row_count']} rows: "
        f"{summary['pass_count']} passed, {summary['fail_count']} failed."
    )
    print(f"Comparison details: {output_path}")
    print(f"Summary: {summary_path}")
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
