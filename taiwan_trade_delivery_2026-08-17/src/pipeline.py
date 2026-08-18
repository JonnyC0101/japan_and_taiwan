"""One-command Taiwan import/export monthly workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

from fetcher import DATA_ENDPOINT, fetch_month, latest_published_month, write_raw
from history import calculate_metrics, merge_history, write_metrics
from reference import (
    TARIFF_DATA_URL, build_reference, download_tariff_csv, load_reference,
)


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data" / "reference" / "taiwan_ccc_84_85.csv"
REFERENCE_MANIFEST = REFERENCE.with_suffix(".manifest.json")
TARIFF_RAW = ROOT / "data" / "reference" / "official_tariff_full.csv"
WRITER = ROOT / "src" / "excel_writer.mjs"


def portable_path(path: Path) -> str:
    """Keep project-local run metadata portable across machines."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _month_shift(month: str, offset: int) -> str:
    year, number = map(int, month.split("-"))
    total = year * 12 + number - 1 + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _month_range(start: str, end: str) -> list[str]:
    result = []
    current = start
    while current <= end:
        result.append(current)
        current = _month_shift(current, 1)
    if not result or result[-1] != end:
        raise ValueError(f"Invalid month range: {start} to {end}")
    return result


def ensure_reference(refresh: bool) -> None:
    if refresh or not REFERENCE.exists():
        metadata = download_tariff_csv(TARIFF_RAW)
        count = build_reference(TARIFF_RAW, REFERENCE, REFERENCE_MANIFEST)
        manifest = json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8"))
        manifest["download"] = metadata
        REFERENCE_MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Built official CCC reference with {count:,} Chapter 84/85 codes.")


def run_writer(flow: str, metrics: Path, output_dir: Path, args: argparse.Namespace) -> None:
    node = args.node
    if not Path(node).exists():
        node = shutil.which(node) or node
    command = [
        str(node), str(WRITER), "--metrics", str(metrics), "--output-dir", str(output_dir),
        "--flow", flow, "--scope", args.excel_scope, "--concurrency", str(args.excel_concurrency),
    ]
    if args.limit_ccc is not None:
        command.extend(["--limit-ccc", str(args.limit_ccc)])
    subprocess.run(command, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automate Taiwan Chapter 84/85 trade workbooks.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--auto", action="store_true", help="Use the newest published month.")
    source.add_argument("--months", help="Comma-separated months, e.g. 2025-07,2026-05,2026-06.")
    source.add_argument("--start-month", help="Inclusive first month (YYYY-MM).")
    parser.add_argument("--end-month", help="Inclusive last month for --start-month.")
    parser.add_argument("--flow", choices=("both", "import", "export"), default="both")
    parser.add_argument("--refresh-months", type=int, default=3)
    parser.add_argument("--refresh-reference", action="store_true")
    parser.add_argument(
        "--reuse-raw", action="store_true",
        help="Reuse a complete existing raw month; incomplete files are fetched again.",
    )
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.03)
    parser.add_argument("--limit-batches", type=int, help="Development-only fetch limit.")
    parser.add_argument("--skip-excel", action="store_true")
    parser.add_argument("--excel-scope", choices=("all", "consolidated", "per-ccc"), default="all")
    parser.add_argument("--limit-ccc", type=int, help="Development-only workbook limit.")
    parser.add_argument("--excel-concurrency", type=int, default=6)
    parser.add_argument("--node", default="node")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_month and not args.end_month:
        args.end_month = args.start_month
    ensure_reference(args.refresh_reference)
    commodities = load_reference(REFERENCE)
    if args.auto:
        latest = latest_published_month()
        months = [_month_shift(latest, offset) for offset in range(-(args.refresh_months - 1), 1)]
    elif args.months:
        months = sorted(set(item.strip() for item in args.months.split(",") if item.strip()))
    else:
        months = _month_range(args.start_month, args.end_month)
    flows = ("import", "export") if args.flow == "both" else (args.flow,)
    summary: dict[str, object] = {
        "status": "complete", "months": months, "flows": {},
        "reference_file": portable_path(REFERENCE), "reference_count": len(commodities),
    }
    for flow in flows:
        raw_paths: list[Path] = []
        manifests: list[dict[str, object]] = []
        for month in months:
            raw_path = ROOT / "data" / "raw" / flow / f"{flow}_{month}.csv"
            manifest_path = raw_path.with_suffix(".manifest.json")
            manifest = None
            if args.reuse_raw and raw_path.exists() and manifest_path.exists():
                candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
                expected = len(commodities) if args.limit_batches is None else min(
                    len(commodities), args.limit_batches * args.batch_size
                )
                if int(candidate.get("ccc_count", -1)) == expected:
                    manifest = candidate
                    print(f"Reusing complete raw file: {raw_path.name}")
            if manifest is None:
                print(f"Fetching Taiwan {flow} {month} ({len(commodities):,} CCC codes) ...")
                records, manifest = fetch_month(
                    flow=flow, month=month, commodities=commodities,
                    concurrency=args.concurrency, batch_size=args.batch_size,
                    min_interval=args.delay, limit_batches=args.limit_batches,
                )
                write_raw(records, raw_path, manifest)
            raw_paths.append(raw_path)
            manifests.append(manifest)
        history_path = ROOT / "data" / "history" / f"{flow}_monthly.csv"
        history_rows, inserted, replaced = merge_history(history_path, raw_paths)
        # Preserve retired CCC codes in the historical audit trail, but only publish
        # workbooks for the current official reference universe. This prevents a
        # tariff revision from leaving obsolete codes in a workbook labelled current.
        current_codes = {commodity.ccc_code for commodity in commodities}
        metric_rows = calculate_metrics(
            [row for row in history_rows if row["ccc_code"] in current_codes]
        )
        metrics_path = ROOT / "data" / "interim" / f"{flow}_metrics.json"
        write_metrics(metrics_path, metric_rows, DATA_ENDPOINT)
        latest_flow_month = max(row["month"] for row in history_rows)
        output_dir = ROOT / "outputs" / "monthly" / latest_flow_month / flow
        if not args.skip_excel:
            run_writer(flow, metrics_path, output_dir, args)
        flow_summary = {
            "raw_files": [portable_path(path) for path in raw_paths],
            "history_file": portable_path(history_path),
            "metrics_file": portable_path(metrics_path),
            "output_directory": portable_path(output_dir), "history_rows": len(history_rows),
            "ccc_count": len(current_codes),
            "inserted_rows": inserted, "replaced_rows": replaced,
            "latest_month": latest_flow_month,
            "fetch_manifests": manifests,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "run_summary.json").write_text(
            json.dumps(flow_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        summary["flows"][flow] = flow_summary
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
