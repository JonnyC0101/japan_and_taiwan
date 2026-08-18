"""Validate delivery coverage, key uniqueness, manifests, and output completeness."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    reference_rows = read_csv(ROOT / "data" / "reference" / "taiwan_ccc_84_85.csv")
    reference = {row["ccc_code"] for row in reference_rows}
    if len(reference) != len(reference_rows) or not reference:
        raise AssertionError("CCC reference is empty or contains duplicates")

    delivery_summary: dict[str, object] = {"reference_count": len(reference), "flows": {}}
    for flow in ("import", "export"):
        history = read_csv(ROOT / "data" / "history" / f"{flow}_monthly.csv")
        keys = [(row["flow"], row["month"], row["ccc_code"]) for row in history]
        if len(keys) != len(set(keys)):
            raise AssertionError(f"Duplicate history keys in {flow}")
        month_counts = Counter(row["month"] for row in history)
        current_history_codes = {row["ccc_code"] for row in history} & reference
        if current_history_codes != reference:
            missing = sorted(reference - current_history_codes)[:5]
            raise AssertionError(f"{flow} history is missing current CCC codes: {missing}")

        latest = max(month_counts)
        output = ROOT / "outputs" / "monthly" / latest / flow
        workbook_codes = {path.stem for path in (output / "by_ccc_code").glob("*.xlsx")}
        if workbook_codes != reference:
            missing = sorted(reference - workbook_codes)[:5]
            extra = sorted(workbook_codes - reference)[:5]
            raise AssertionError(f"{flow} workbook mismatch; missing={missing}, extra={extra}")
        if not (output / f"all_ccc_{flow}.xlsx").exists():
            raise AssertionError(f"Missing consolidated {flow} workbook")

        raw_months = []
        for manifest_path in sorted((ROOT / "data" / "raw" / flow).glob("*.manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Old manifests are valid historical evidence even after an annual tariff
            # revision. Only require that their declared count matches their raw CSV.
            if int(manifest["amount_mismatch_count"]) != 0:
                raise AssertionError(f"Quantity/weight amount mismatch: {manifest_path}")
            raw_csv = manifest_path.with_name(manifest_path.name.replace(".manifest.json", ".csv"))
            if len(read_csv(raw_csv)) != int(manifest["ccc_count"]):
                raise AssertionError(f"Incomplete raw CSV: {raw_csv}")
            raw_months.append(manifest["month"])

        delivery_summary["flows"][flow] = {
            "history_rows": len(history),
            "history_months": sorted(month_counts),
            "raw_months": raw_months,
            "per_ccc_workbooks": len(workbook_codes),
            "latest_month": latest,
        }

    sidecars = list(ROOT.rglob("*.inspect.ndjson"))
    if sidecars:
        raise AssertionError(f"Inspection sidecars remain in delivery: {sidecars[:3]}")
    print(json.dumps(delivery_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
