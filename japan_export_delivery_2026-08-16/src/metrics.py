"""Calculate auditable monthly and quarterly HS-level export metrics."""

from __future__ import annotations

import json
import csv
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from data_model import NormalizedRow


@dataclass(frozen=True)
class MetricRow:
    direction: str
    hs_code: str
    month: str
    unit1: str
    quantity1: int | None
    unit2: str
    volume: int | None
    value_thousand_yen: int
    value_million_yen: float
    asp_thousand_yen_per_unit2: float | None
    asp_3mma: float | None
    asp_mom: float | None
    volume_mom: float | None
    value_mom: float | None
    asp_yoy: float | None
    volume_yoy: float | None
    value_yoy: float | None
    value_quarter_thousand_yen: int | None
    quarter_value_qoq: float | None
    quarter_value_yoy: float | None
    record_status: str
    fetched_at_utc: str


def month_date(value: str) -> date:
    year, month = (int(part) for part in value.split("-"))
    return date(year, month, 1)


def shift_month(value: str, delta: int) -> str:
    current = month_date(value)
    absolute = current.year * 12 + current.month - 1 + delta
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def change(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def calculate_metrics(rows: Iterable[NormalizedRow]) -> list[MetricRow]:
    by_hs: dict[str, dict[str, NormalizedRow]] = {}
    for row in rows:
        if row.direction != "export":
            continue
        months = by_hs.setdefault(row.hs_code, {})
        if row.month in months:
            raise ValueError(f"Duplicate normalized row for {row.month}, HS {row.hs_code}")
        months[row.month] = row

    output: list[MetricRow] = []
    for code in sorted(by_hs):
        source = by_hs[code]
        asp_by_month = {
            month: (
                row.value_thousand_yen / row.quantity2
                if row.quantity2 not in (None, 0)
                else None
            )
            for month, row in source.items()
        }
        quarter_values: dict[str, int] = {}
        for month, row in source.items():
            month_number = month_date(month).month
            if month_number in (3, 6, 9, 12):
                three = [shift_month(month, -2), shift_month(month, -1), month]
                if all(item in source for item in three):
                    quarter_values[month] = sum(source[item].value_thousand_yen for item in three)

        for month in sorted(source):
            row = source[month]
            asp = asp_by_month[month]
            previous_month = shift_month(month, -1)
            previous_year = shift_month(month, -12)
            mma_months = [shift_month(month, -2), previous_month, month]
            mma_values = [asp_by_month.get(item) for item in mma_months]
            asp_3mma = (
                sum(value for value in mma_values if value is not None) / 3
                if all(value is not None for value in mma_values)
                else None
            )
            quarter_value = quarter_values.get(month)
            output.append(
                MetricRow(
                    direction=row.direction, hs_code=code, month=month,
                    unit1=row.unit1, quantity1=row.quantity1, unit2=row.unit2,
                    volume=row.quantity2, value_thousand_yen=row.value_thousand_yen,
                    value_million_yen=row.value_thousand_yen / 1000,
                    asp_thousand_yen_per_unit2=asp, asp_3mma=asp_3mma,
                    asp_mom=change(asp, asp_by_month.get(previous_month)),
                    volume_mom=change(row.quantity2, source.get(previous_month).quantity2 if previous_month in source else None),
                    value_mom=change(row.value_thousand_yen, source.get(previous_month).value_thousand_yen if previous_month in source else None),
                    asp_yoy=change(asp, asp_by_month.get(previous_year)),
                    volume_yoy=change(row.quantity2, source.get(previous_year).quantity2 if previous_year in source else None),
                    value_yoy=change(row.value_thousand_yen, source.get(previous_year).value_thousand_yen if previous_year in source else None),
                    value_quarter_thousand_yen=quarter_value,
                    quarter_value_qoq=change(quarter_value, quarter_values.get(shift_month(month, -3))),
                    quarter_value_yoy=change(quarter_value, quarter_values.get(shift_month(month, -12))),
                    record_status=row.record_status, fetched_at_utc=row.fetched_at_utc,
                )
            )
    return output


def load_hs_metadata(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return {
            (row.get("HS Code") or "").strip().strip("'"): {
                "source_codes": (row.get("Source Code(s)") or "").strip(),
                "product_types": (row.get("Product Types") or "").strip(),
                "companies": (row.get("Companies") or "").strip(),
                "mapping_action": (row.get("Mapping Action") or "").strip(),
                "mapping_note": (row.get("Mapping Note") or "").strip(),
                "official_schedule_url": (row.get("Official Schedule URL") or "").strip(),
            }
            for row in reader
            if (row.get("HS Code") or "").strip()
        }


def write_metrics_json(
    path: Path,
    rows: Iterable[MetricRow],
    source_url: str,
    reference_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = {
        "schema_version": 1,
        "source_url": source_url,
        "trade_value_basis": "Export values are FOB and expressed in thousand JPY.",
        "asp_definition": "value_thousand_yen / quantity2",
        "hs_metadata": load_hs_metadata(reference_path),
        "rows": [asdict(row) for row in rows],
    }
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
