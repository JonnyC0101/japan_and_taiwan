"""Idempotent history storage for normalized monthly Customs rows."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from data_model import NormalizedRow, read_normalized_csv, write_normalized_csv


def merge_history(path: Path, incoming: Iterable[NormalizedRow]) -> tuple[list[NormalizedRow], int, int]:
    existing = read_normalized_csv(path)
    by_key = {(row.direction, row.month, row.hs_code): row for row in existing}
    inserted = 0
    replaced = 0
    for row in incoming:
        key = (row.direction, row.month, row.hs_code)
        if key in by_key:
            replaced += 1
        else:
            inserted += 1
        by_key[key] = row
    merged = sorted(by_key.values(), key=lambda row: (row.direction, row.hs_code, row.month))
    write_normalized_csv(path, merged)
    return merged, inserted, replaced
