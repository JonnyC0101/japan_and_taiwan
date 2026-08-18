"""Build the queryable Japan-export HS reference from the business mapping.

The user-supplied mapping is preserved verbatim.  This script creates a second,
auditable table whose HS Code column contains only official nine-digit export
leaves.  Parent/import-style codes are expanded through the reviewed correction
table, and repeated official codes are merged without losing their source rows.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = PROJECT_ROOT / "data" / "reference" / "export_hs_product_mapping.csv"
DEFAULT_CORRECTIONS = PROJECT_ROOT / "data" / "reference" / "export_code_corrections.csv"
DEFAULT_OFFICIAL = [
    PROJECT_ROOT / "data" / "reference" / "2026" / "official_export_values_2026-06.csv",
    PROJECT_ROOT / "data" / "reference" / "2025" / "official_export_values_2025.csv",
]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv"
DEFAULT_FULL_CHAPTERS = ("84", "85")
CODE_PATTERN = re.compile(r"^\d{9}$")


def code(value: str | None) -> str:
    normalized = re.sub(r"\D", "", value or "")
    if not CODE_PATTERN.fullmatch(normalized):
        raise ValueError(f"Expected a 9-digit code, received {value!r}")
    return normalized


def split_terms(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split("；") if item.strip()]


def load_official_units(paths: list[Path]) -> dict[str, tuple[str, str]]:
    units: dict[str, tuple[str, str]] = {}
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                raw_hs = re.sub(r"[^0-9A-Za-z]", "", row.get("HS") or "")
                if not CODE_PATTERN.fullmatch(raw_hs):
                    # e-Stat also publishes confidentiality aggregates such as
                    # 15XXXXXXA; these are not queryable nine-digit HS leaves.
                    continue
                hs_code = raw_hs
                candidate = ((row.get("Unit1") or "").strip(), (row.get("Unit2") or "").strip())
                if hs_code not in units:
                    units[hs_code] = candidate
    return units


def load_corrections(path: Path) -> dict[str, list[dict[str, str]]]:
    corrections: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            source_code = code(row.get("Source Code"))
            row["Official Export Code"] = code(row.get("Official Export Code"))
            corrections[source_code].append(row)
    return dict(corrections)


def build(
    mapping: Path,
    correction_path: Path,
    official_paths: list[Path],
    full_chapters: tuple[str, ...] = DEFAULT_FULL_CHAPTERS,
) -> list[dict[str, str]]:
    official_units = load_official_units(official_paths)
    corrections = load_corrections(correction_path)
    aggregated: dict[str, dict[str, object]] = {}

    # Match the import project's breadth: include every official leaf in
    # Chapters 84 and 85.  The curated business mapping below then adds its
    # cross-chapter semiconductor materials and enriches matching 84/85 rows.
    for official_code in sorted(official_units):
        if not official_code.startswith(full_chapters):
            continue
        chapter = official_code[:2]
        aggregated[official_code] = {
            "sources": [official_code],
            "products": [f"日本出口第{chapter}章全量覆盖（原始业务映射未单独分类时使用）"],
            "companies": [],
            "actions": ["full_chapter_coverage"],
            "reasons": [f"Included because the production scope covers every official export leaf in Chapter {chapter}."],
            "urls": [f"https://www.customs.go.jp/yusyutu/2025_01_01/data/j_{chapter}.htm"],
        }

    with mapping.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"编码", "对应的产品类型", "有哪些公司在做"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Business mapping must contain {sorted(required)}")
        for row_number, row in enumerate(reader, start=2):
            source_code = code(row.get("编码"))
            replacements = corrections.get(source_code)
            targets = replacements or [{
                "Official Export Code": source_code,
                "Action": "direct",
                "Reason": "The supplied code is already an official export leaf.",
                "Official Schedule URL": "https://www.customs.go.jp/yusyutu/2025_01_01/index.htm",
            }]
            for correction in targets:
                official_code = correction["Official Export Code"]
                if official_code not in official_units:
                    raise ValueError(
                        f"Official export code {official_code} (mapping row {row_number}) "
                        "is absent from the supplied official e-Stat tables."
                    )
                entry = aggregated.setdefault(official_code, {
                    "sources": [], "products": [], "companies": [], "actions": [],
                    "reasons": [], "urls": [],
                })
                mapped_products = split_terms(row.get("对应的产品类型"))
                if mapped_products and entry["actions"] == ["full_chapter_coverage"]:
                    entry["products"].clear()
                for key, values in (
                    ("sources", [source_code]),
                    ("products", mapped_products),
                    ("companies", split_terms(row.get("有哪些公司在做"))),
                    ("actions", [correction.get("Action", "")]),
                    ("reasons", [correction.get("Reason", "")]),
                    ("urls", [correction.get("Official Schedule URL", "")]),
                ):
                    for value in values:
                        if value and value not in entry[key]:
                            entry[key].append(value)

    output: list[dict[str, str]] = []
    for official_code, entry in sorted(aggregated.items()):
        unit1, unit2 = official_units[official_code]
        if not unit2:
            raise ValueError(f"Official export code {official_code} has no Unit2")
        output.append({
            "HS Code": official_code,
            "Source Code(s)": "；".join(entry["sources"]),
            "Product Types": "；".join(entry["products"]),
            "Companies": "；".join(entry["companies"]),
            "Unit1": unit1,
            "Unit2": unit2,
            "Mapping Action": "；".join(entry["actions"]),
            "Mapping Note": "；".join(entry["reasons"]),
            "Official Schedule URL": "；".join(entry["urls"]),
        })
    return output


def write(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    fieldnames = list(rows[0])
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the official Japan export HS reference.")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument("--official", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--full-chapter",
        action="append",
        help="Two-digit chapter to include in full (default: 84 and 85).",
    )
    args = parser.parse_args()
    official = args.official or DEFAULT_OFFICIAL
    chapters = tuple(args.full_chapter or DEFAULT_FULL_CHAPTERS)
    if any(len(item) != 2 or not item.isdigit() for item in chapters):
        raise ValueError("--full-chapter values must be two digits")
    rows = build(args.mapping, args.corrections, official, chapters)
    write(args.output, rows)
    print(f"Wrote {len(rows)} official export HS codes to {args.output}")


if __name__ == "__main__":
    main()
