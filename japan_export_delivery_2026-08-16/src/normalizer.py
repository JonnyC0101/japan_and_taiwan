"""Normalize fetched Customs rows and materialize omitted all-zero HS months."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from data_model import NormalizedRow, normalize_hs_code, parse_optional_integer


class NormalizationError(RuntimeError):
    pass


def load_reference_units(path: Path) -> dict[str, tuple[str, str]]:
    """Load the current HS universe and its two official quantity units."""
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames or []
        code_field = "HS" if "HS" in fieldnames else "HS Code" if "HS Code" in fieldnames else None
        if code_field is None:
            raise NormalizationError(f"Reference file has no HS/HS Code column: {path}")
        units: dict[str, tuple[str, str]] = {}
        for number, row in enumerate(reader, start=2):
            code = normalize_hs_code(row.get(code_field), f"{path} row {number}")
            unit1 = (row.get("Unit1") or row.get("unit1") or "").strip()
            unit2 = (row.get("Unit2") or row.get("unit2") or "").strip()
            if code in units and units[code] != (unit1, unit2):
                raise NormalizationError(f"Conflicting units for HS {code} in {path}")
            if not unit2:
                raise NormalizationError(f"HS {code} has no Unit2 in {path}")
            units[code] = (unit1, unit2)
    if not units:
        raise NormalizationError(f"Reference file is empty: {path}")
    return units


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NormalizationError(f"Cannot read manifest {path}: {error}") from error
    if manifest.get("status") != "complete":
        raise NormalizationError(f"Manifest is not complete: {path}")
    if manifest.get("direction") != "export":
        raise NormalizationError("The production normalizer accepts Japan export data only.")
    if not isinstance(manifest.get("months"), dict) or not manifest["months"]:
        raise NormalizationError(f"Manifest contains no completed months: {path}")
    return manifest


def load_raw_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    required = {
        "direction", "month", "hs_code", "unit1", "quantity1", "unit2", "quantity2",
        "value_thousand_yen", "ytd_quantity1", "ytd_quantity2", "ytd_value_thousand_yen",
        "fetched_at_utc",
    }
    output: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise NormalizationError(f"Raw CSV is missing columns: {', '.join(missing)}")
        for number, row in enumerate(reader, start=2):
            direction = row["direction"].strip().lower()
            month = row["month"].strip()
            code = normalize_hs_code(row["hs_code"], f"{path} row {number}")
            key = (month, code)
            if direction != "export":
                raise NormalizationError(f"Unexpected direction at {path} row {number}: {direction}")
            if key in output:
                raise NormalizationError(f"Duplicate raw row for {month}, HS {code}")
            output[key] = row
    return output


def normalize_files(raw_path: Path, manifest_path: Path, reference_path: Path) -> list[NormalizedRow]:
    units = load_reference_units(reference_path)
    manifest = load_manifest(manifest_path)
    raw = load_raw_rows(raw_path)
    target_codes = set(units)
    completed_at = str(manifest.get("completed_at_utc") or "")
    normalized: list[NormalizedRow] = []

    manifest_months = set(manifest["months"])
    unexpected_months = {month for month, _ in raw} - manifest_months
    if unexpected_months:
        raise NormalizationError(f"Raw CSV contains months absent from manifest: {sorted(unexpected_months)}")

    for month in sorted(manifest_months):
        info = manifest["months"][month]
        if not isinstance(info, dict):
            raise NormalizationError(f"Invalid manifest month entry: {month}")
        returned_count = int(info.get("returned_hs_count", 0))
        month_raw_count = sum(1 for raw_month, _ in raw if raw_month == month)
        if returned_count == 0 or month_raw_count == 0:
            raise NormalizationError(
                f"{month} returned no HS rows. It may not be published yet; history was not updated."
            )
        if returned_count != month_raw_count:
            raise NormalizationError(
                f"Manifest/raw count mismatch for {month}: {returned_count} vs {month_raw_count}"
            )

        for code in sorted(target_codes):
            raw_row = raw.get((month, code))
            reference_unit1, reference_unit2 = units[code]
            if raw_row is None:
                normalized.append(
                    NormalizedRow(
                        direction="export", month=month, hs_code=code,
                        unit1=reference_unit1, quantity1=0 if reference_unit1 else None,
                        unit2=reference_unit2, quantity2=0, value_thousand_yen=0,
                        ytd_quantity1=None, ytd_quantity2=None, ytd_value_thousand_yen=None,
                        fetched_at_utc=completed_at, record_status="zero_not_returned",
                    )
                )
                continue

            unit1 = raw_row["unit1"].strip()
            unit2 = raw_row["unit2"].strip()
            if not unit2:
                raise NormalizationError(f"Returned HS {code} has no Unit2 in {month}")
            normalized.append(
                NormalizedRow(
                    direction="export", month=month, hs_code=code,
                    unit1=unit1, quantity1=parse_optional_integer(raw_row["quantity1"], "quantity1"),
                    unit2=unit2, quantity2=parse_optional_integer(raw_row["quantity2"], "quantity2"),
                    value_thousand_yen=parse_optional_integer(
                        raw_row["value_thousand_yen"], "value_thousand_yen"
                    ) or 0,
                    ytd_quantity1=parse_optional_integer(raw_row["ytd_quantity1"], "ytd_quantity1"),
                    ytd_quantity2=parse_optional_integer(raw_row["ytd_quantity2"], "ytd_quantity2"),
                    ytd_value_thousand_yen=parse_optional_integer(
                        raw_row["ytd_value_thousand_yen"], "ytd_value_thousand_yen"
                    ),
                    fetched_at_utc=raw_row["fetched_at_utc"].strip(), record_status="reported",
                )
            )

    expected = len(manifest_months) * len(target_codes)
    if len(normalized) != expected:
        raise NormalizationError(f"Expected {expected} normalized rows, produced {len(normalized)}")
    return normalized
