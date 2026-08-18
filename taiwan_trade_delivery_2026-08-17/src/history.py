"""History storage and business metric calculations."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from fetcher import RAW_FIELDS


HISTORY_FIELDS = RAW_FIELDS


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def merge_history(history_path: Path, raw_paths: list[Path]) -> tuple[list[dict[str, str]], int, int]:
    existing = _read(history_path)
    keyed = {(row["flow"], row["month"], row["ccc_code"]): row for row in existing}
    inserted = replaced = 0
    for raw_path in raw_paths:
        for row in _read(raw_path):
            key = (row["flow"], row["month"], row["ccc_code"])
            if key in keyed:
                replaced += 1
            else:
                inserted += 1
            keyed[key] = row
    rows = sorted(keyed.values(), key=lambda row: (row["ccc_code"], row["month"]))
    _write(history_path, rows)
    return rows, inserted, replaced


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _ratio(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def calculate_metrics(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["ccc_code"], []).append(row)
    output: list[dict[str, object]] = []
    for code, group in sorted(groups.items()):
        group.sort(key=lambda row: row["month"])
        by_month = {row["month"]: row for row in group}
        unit_prices: list[float | None] = []
        for position, row in enumerate(group):
            value = _float(row["value_usd"])
            quantity = _float(row["quantity"])
            weight = _float(row["weight_kg"])
            unit_price = None if value is None or quantity in (None, 0) else value / quantity
            price_per_kg = None if value is None or weight in (None, 0) else value / weight
            unit_prices.append(unit_price)
            year, month = map(int, row["month"].split("-"))
            previous_key = f"{year - 1:04d}-{month:02d}"
            previous = by_month.get(previous_key)
            prior_row = group[position - 1] if position > 0 else None
            prior_consecutive = False
            if prior_row:
                prior_date = datetime.strptime(prior_row["month"], "%Y-%m")
                current_date = datetime.strptime(row["month"], "%Y-%m")
                prior_consecutive = (current_date.year * 12 + current_date.month) - (prior_date.year * 12 + prior_date.month) == 1
            previous_value = _float(previous["value_usd"]) if previous else None
            previous_quantity = _float(previous["quantity"]) if previous else None
            previous_weight = _float(previous["weight_kg"]) if previous else None
            previous_unit_price = (
                None if previous_value is None or previous_quantity in (None, 0)
                else previous_value / previous_quantity
            )
            previous_kg_price = (
                None if previous_value is None or previous_weight in (None, 0)
                else previous_value / previous_weight
            )
            prior_value = _float(prior_row["value_usd"]) if prior_consecutive and prior_row else None
            prior_quantity = _float(prior_row["quantity"]) if prior_consecutive and prior_row else None
            prior_weight = _float(prior_row["weight_kg"]) if prior_consecutive and prior_row else None
            prior_unit_price = None if prior_value is None or prior_quantity in (None, 0) else prior_value / prior_quantity
            prior_kg_price = None if prior_value is None or prior_weight in (None, 0) else prior_value / prior_weight
            has_consecutive_three = False
            if position >= 2:
                month_numbers = []
                for candidate in group[position - 2:position + 1]:
                    candidate_year, candidate_month = map(int, candidate["month"].split("-"))
                    month_numbers.append(candidate_year * 12 + candidate_month)
                has_consecutive_three = (
                    month_numbers[1] - month_numbers[0] == 1
                    and month_numbers[2] - month_numbers[1] == 1
                )
            output.append({
                **row,
                "quantity": quantity, "weight_kg": weight, "value_usd": value,
                "unit_value_usd": unit_price, "unit_value_usd_per_kg": price_per_kg,
                "unit_value_3mma": (
                    sum(item for item in unit_prices[-3:] if item is not None) / 3
                    if has_consecutive_three and all(item is not None for item in unit_prices[-3:]) else None
                ),
                "quantity_mom": _ratio(quantity, prior_quantity),
                "weight_mom": _ratio(weight, prior_weight),
                "value_mom": _ratio(value, prior_value),
                "unit_value_mom": _ratio(unit_price, prior_unit_price),
                "kg_value_mom": _ratio(price_per_kg, prior_kg_price),
                "quantity_yoy": _ratio(quantity, previous_quantity),
                "weight_yoy": _ratio(weight, previous_weight),
                "value_yoy": _ratio(value, previous_value),
                "unit_value_yoy": _ratio(unit_price, previous_unit_price),
                "kg_value_yoy": _ratio(price_per_kg, previous_kg_price),
            })
    return output


def write_metrics(path: Path, rows: list[dict[str, object]], source_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_url": source_url,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
