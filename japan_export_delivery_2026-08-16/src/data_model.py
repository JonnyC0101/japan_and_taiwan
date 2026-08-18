"""Shared row models and CSV helpers for the production export pipeline."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class NormalizedRow:
    direction: str
    month: str
    hs_code: str
    unit1: str
    quantity1: int | None
    unit2: str
    quantity2: int | None
    value_thousand_yen: int
    ytd_quantity1: int | None
    ytd_quantity2: int | None
    ytd_value_thousand_yen: int | None
    fetched_at_utc: str
    record_status: str


NORMALIZED_FIELDS = list(NormalizedRow.__dataclass_fields__)


def parse_optional_integer(value: str | int | None, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).replace(",", "").strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError as error:
        raise ValueError(f"Invalid integer in {field}: {value!r}") from error


def normalize_hs_code(value: str | None, context: str) -> str:
    code = (value or "").strip().strip("'\"").strip()
    if len(code) != 9 or not code.isdigit():
        raise ValueError(f"Invalid HS code in {context}: {value!r}")
    return code


def read_normalized_csv(path: Path) -> list[NormalizedRow]:
    if not path.exists():
        return []
    rows: list[NormalizedRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = [field for field in NORMALIZED_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"History CSV is missing columns: {', '.join(missing)}")
        for number, row in enumerate(reader, start=2):
            rows.append(
                NormalizedRow(
                    direction=row["direction"].strip().lower(),
                    month=row["month"].strip(),
                    hs_code=normalize_hs_code(row["hs_code"], f"{path} row {number}"),
                    unit1=row["unit1"].strip(),
                    quantity1=parse_optional_integer(row["quantity1"], "quantity1"),
                    unit2=row["unit2"].strip(),
                    quantity2=parse_optional_integer(row["quantity2"], "quantity2"),
                    value_thousand_yen=parse_optional_integer(
                        row["value_thousand_yen"], "value_thousand_yen"
                    )
                    or 0,
                    ytd_quantity1=parse_optional_integer(row["ytd_quantity1"], "ytd_quantity1"),
                    ytd_quantity2=parse_optional_integer(row["ytd_quantity2"], "ytd_quantity2"),
                    ytd_value_thousand_yen=parse_optional_integer(
                        row["ytd_value_thousand_yen"], "ytd_value_thousand_yen"
                    ),
                    fetched_at_utc=row["fetched_at_utc"].strip(),
                    record_status=row["record_status"].strip(),
                )
            )
    return rows


def write_normalized_csv(path: Path, rows: Iterable[NormalizedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    ordered = sorted(rows, key=lambda row: (row.direction, row.month, row.hs_code))
    try:
        with temporary.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=NORMALIZED_FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in ordered:
                output = asdict(row)
                output["hs_code"] = f"'{row.hs_code}"
                writer.writerow(output)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
