"""Reconcile Customs website raw exports with official e-Stat wide CSV tables."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def integer(value: str | None) -> int:
    return int((value or "0").replace(",", "") or 0)


def load_raw(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return {
            (row["month"], re.sub(r"\D", "", row["hs_code"])): row
            for row in csv.DictReader(source)
        }


def compare(raw_path: Path, official_path: Path, year: int, through_month: int) -> dict[str, object]:
    raw = load_raw(raw_path)
    mismatches: list[dict[str, object]] = []
    checked = 0
    with official_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            code = re.sub(r"\D", "", row["HS"])
            if len(code) != 9:
                continue
            for month_number, label in enumerate(MONTHS[:through_month], start=1):
                key = (f"{year:04d}-{month_number:02d}", code)
                actual = raw.get(key)
                if actual is None:
                    continue
                checked += 1
                expected = {
                    "unit1": (row.get("Unit1") or "").strip(),
                    "unit2": (row.get("Unit2") or "").strip(),
                    "quantity1": integer(row.get(f"Quantity1-{label}")),
                    "quantity2": integer(row.get(f"Quantity2-{label}")),
                    "value": integer(row.get(f"Value-{label}")),
                }
                observed = {
                    "unit1": (actual.get("unit1") or "").strip(),
                    "unit2": (actual.get("unit2") or "").strip(),
                    "quantity1": integer(actual.get("quantity1")),
                    "quantity2": integer(actual.get("quantity2")),
                    "value": integer(actual.get("value_thousand_yen")),
                }
                if expected != observed:
                    mismatches.append({"month": key[0], "hs_code": code, "expected": expected, "actual": observed})
    raw_count = len(raw)
    result = {
        "raw_file": str(raw_path),
        "official_file": str(official_path),
        "raw_rows": raw_count,
        "checked_rows": checked,
        "missing_from_official": raw_count - checked,
        "mismatch_count": len(mismatches),
        "sample_mismatches": mismatches[:20],
    }
    result["status"] = "pass" if checked == raw_count and not mismatches else "fail"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--through-month", type=int, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.raw, args.official, args.year, args.through_month)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
