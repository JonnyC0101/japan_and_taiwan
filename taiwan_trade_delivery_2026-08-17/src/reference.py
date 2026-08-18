"""Build and load the official Taiwan CCC reference universe."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


TARIFF_DATA_URL = "https://opendata.customs.gov.tw/data/80871/csv.csv"
REFERENCE_FIELDS = (
    "ccc_code", "hs6", "hs8", "commodity_name_zh", "commodity_name_en",
    "quantity_unit", "weight_unit", "source_url", "source_last_modified",
)


@dataclass(frozen=True)
class Commodity:
    ccc_code: str
    hs6: str
    hs8: str
    commodity_name_zh: str
    commodity_name_en: str
    quantity_unit: str
    weight_unit: str
    source_url: str
    source_last_modified: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_tariff_csv(destination: Path, retries: int = 6) -> dict[str, object]:
    """Download the full official tariff CSV and reject truncated responses."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    headers: dict[str, str] = {}
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                TARIFF_DATA_URL,
                headers={"User-Agent": "TaiwanTradeWorkflow/1.0 (+official-statistics-research)"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                expected = int(headers.get("content-length", "0") or 0)
                with temporary.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
            actual = temporary.stat().st_size
            if expected and actual != expected:
                raise IOError(f"Truncated tariff CSV: expected {expected} bytes, received {actual}")
            temporary.replace(destination)
            return {
                "source_url": TARIFF_DATA_URL,
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_last_modified": headers.get("last-modified", ""),
                "content_length": actual,
                "sha256": _sha256(destination),
            }
        except Exception:
            if temporary.exists():
                temporary.unlink()
            if attempt == retries:
                raise
            time.sleep(min(2 ** (attempt - 1), 16))
    raise AssertionError("unreachable")


def build_reference(source_csv: Path, output_csv: Path, manifest_path: Path) -> int:
    """Filter the official tariff universe to active Chapter 84 and 85 CCC codes."""
    rows: list[dict[str, str]] = []
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            code = (raw.get("貨品分類號列") or "").strip()
            if not re.fullmatch(r"(?:84|85)\d{9}", code):
                continue
            rows.append({
                "ccc_code": code,
                "hs6": code[:6],
                "hs8": code[:8],
                "commodity_name_zh": (raw.get("中文貨名") or "").strip(),
                "commodity_name_en": (raw.get("英文貨名") or "").strip(),
                "quantity_unit": (raw.get("統計數量單位") or "").strip(),
                "weight_unit": (raw.get("統計重量單位") or "KGM").strip() or "KGM",
                "source_url": TARIFF_DATA_URL,
                "source_last_modified": "",
            })
    rows.sort(key=lambda row: row["ccc_code"])
    if not rows:
        raise ValueError("No Chapter 84/85 CCC codes were found in the tariff CSV")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REFERENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_csv),
        "source_sha256": _sha256(source_csv),
        "reference_sha256": _sha256(output_csv),
        "ccc_count": len(rows),
        "chapter_counts": {
            "84": sum(row["ccc_code"].startswith("84") for row in rows),
            "85": sum(row["ccc_code"].startswith("85") for row in rows),
        },
        "quantity_unit_count": sum(bool(row["quantity_unit"]) for row in rows),
        "source_url": TARIFF_DATA_URL,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


def load_reference(path: Path) -> list[Commodity]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [Commodity(**{field: (row.get(field) or "") for field in REFERENCE_FIELDS})
                for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError(f"Reference is empty: {path}")
    if len({row.ccc_code for row in rows}) != len(rows):
        raise ValueError(f"Duplicate CCC codes in reference: {path}")
    return sorted(rows, key=lambda row: row.ccc_code)


def make_batches(commodities: list[Commodity], batch_size: int = 20) -> list[list[Commodity]]:
    if not 1 <= batch_size <= 20:
        raise ValueError("The official chart endpoint supports batch sizes from 1 to 20")
    ordered = sorted(commodities, key=lambda row: row.ccc_code)
    return [ordered[index:index + batch_size] for index in range(0, len(ordered), batch_size)]

