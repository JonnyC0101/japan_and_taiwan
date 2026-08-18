"""One-command production workflow for Japan export quantity/value workbooks."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

from fetcher import SEARCH_URL, fetch_to_files, load_hs_codes, parse_month
from history_store import merge_history
from metrics import calculate_metrics, shift_month, write_metrics_json
from normalizer import NormalizationError, normalize_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HS_FILE = PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv"
DEFAULT_REFERENCE = PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv"
DEFAULT_HISTORY = PROJECT_ROOT / "data" / "history" / "export_monthly.csv"
DEFAULT_METRICS = PROJECT_ROOT / "data" / "interim" / "export_metrics.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "monthly"
DEFAULT_WRITER = PROJECT_ROOT / "src" / "excel_writer.mjs"


def portable_path(path: Path) -> str:
    """Keep project-local run metadata portable across machines."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def previous_month(today: date, offset: int = 1) -> date:
    key = shift_month(f"{today.year:04d}-{today.month:02d}", -offset)
    return parse_month(key)


def fetch_range(
    *, start_month: date, end_month: date, codes: list[str], raw_dir: Path, delay: float
) -> tuple[Path, Path, dict[str, object]]:
    label = (
        start_month.strftime("%Y-%m")
        if start_month == end_month
        else f"{start_month:%Y-%m}_to_{end_month:%Y-%m}"
    )
    raw_path = raw_dir / f"export_{label}.csv"
    manifest_path = raw_path.with_suffix(".manifest.json")
    manifest = fetch_to_files(
        direction="export", start_month=start_month, end_month=end_month,
        codes=codes, output_path=raw_path, manifest_path=manifest_path,
        delay_seconds=delay,
    )
    return raw_path, manifest_path, manifest


def discover_latest_month(
    *, codes: list[str], raw_dir: Path, delay: float, max_lookback: int
) -> date:
    """Find the newest published month without treating a no-result page as zero trade."""
    for offset in range(1, max_lookback + 1):
        candidate = previous_month(date.today(), offset)
        print(f"Checking whether {candidate:%Y-%m} is published ...")
        _, _, manifest = fetch_range(
            start_month=candidate, end_month=candidate, codes=codes,
            raw_dir=raw_dir / "discovery", delay=delay,
        )
        months = manifest["months"]
        returned = int(months[candidate.strftime("%Y-%m")]["returned_hs_count"])
        if returned > 0:
            print(f"Latest available month is {candidate:%Y-%m} ({returned} returned HS rows).")
            return candidate
    raise RuntimeError(
        f"No published month found in the previous {max_lookback} months. "
        "Check the Japan Customs site and request parameters."
    )


def run_excel_writer(
    *, metrics_path: Path, output_dir: Path, scope: str, node_command: str,
    writer_script: Path, limit_hs: int | None, expected_hs_count: int,
) -> None:
    node = shutil.which(node_command) if not Path(node_command).exists() else node_command
    if not node:
        raise RuntimeError(
            f"Node executable not found: {node_command}. Set --node to a valid Node.js executable."
        )
    command = [
        str(node), str(writer_script), "--metrics", str(metrics_path),
        "--output-dir", str(output_dir), "--scope", scope,
    ]
    if limit_hs is not None:
        command.extend(["--limit-hs", str(limit_hs)])
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode == 0:
        return
    expected_per_hs = min(expected_hs_count, limit_hs) if limit_hs is not None else expected_hs_count
    consolidated_ok = scope == "per-hs" or (output_dir / "all_hs_export.xlsx").exists()
    per_hs_ok = scope == "consolidated" or len(list((output_dir / "by_hs_code").glob("*.xlsx"))) == expected_per_hs
    if consolidated_ok and per_hs_ok:
        print(
            "Excel writer returned a non-zero wrapper status, but all expected XLSX files "
            "exist. Continuing after output-count verification."
        )
        return
    raise subprocess.CalledProcessError(result.returncode, command)


def write_run_summary(path: Path, summary: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch, normalize, merge, calculate, and export Japan export data."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--auto", action="store_true", help="Discover the newest published month.")
    source.add_argument("--start-month", type=parse_month, help="First live month (YYYY-MM).")
    source.add_argument("--from-raw", type=Path, help="Use an existing fetcher raw CSV instead of the website.")
    parser.add_argument("--end-month", type=parse_month)
    parser.add_argument("--manifest", type=Path, help="Manifest for --from-raw.")
    parser.add_argument("--refresh-months", type=int, default=2)
    parser.add_argument("--max-lookback", type=int, default=4)
    parser.add_argument("--hs-file", type=Path, default=DEFAULT_HS_FILE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--skip-excel", action="store_true")
    parser.add_argument("--excel-scope", choices=("all", "consolidated", "per-hs"), default="all")
    parser.add_argument("--limit-hs", type=int, help="Development-only limit for per-HS workbooks.")
    parser.add_argument("--node", default="node")
    parser.add_argument("--writer-script", type=Path, default=DEFAULT_WRITER)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.refresh_months < 1 or args.max_lookback < 1:
        raise ValueError("--refresh-months and --max-lookback must be positive.")
    if args.delay < 0:
        raise ValueError("--delay must not be negative.")

    hs_file = args.hs_file.resolve()
    reference = args.reference.resolve()
    history_path = args.history.resolve()
    metrics_path = args.metrics.resolve()
    output_root = args.output_root.resolve()
    codes = load_hs_codes(hs_file)

    if args.from_raw:
        raw_path = args.from_raw.resolve()
        manifest_path = (
            args.manifest.resolve() if args.manifest else raw_path.with_suffix(".manifest.json")
        )
    else:
        raw_dir = PROJECT_ROOT / "data" / "raw"
        if args.auto:
            latest = discover_latest_month(
                codes=codes, raw_dir=raw_dir, delay=args.delay, max_lookback=args.max_lookback
            )
            start = parse_month(shift_month(latest.strftime("%Y-%m"), -(args.refresh_months - 1)))
            end = latest
        else:
            start = args.start_month
            end = args.end_month or args.start_month
            if start is None or end is None:
                raise ValueError("A live run needs --start-month.")
        raw_path, manifest_path, _ = fetch_range(
            start_month=start, end_month=end, codes=codes, raw_dir=raw_dir, delay=args.delay
        )

    incoming = normalize_files(raw_path, manifest_path, reference)
    history, inserted, replaced = merge_history(history_path, incoming)
    metric_rows = calculate_metrics(history)
    write_metrics_json(metrics_path, metric_rows, SEARCH_URL, reference)
    latest_month = max(row.month for row in history)
    output_dir = output_root / latest_month

    if not args.skip_excel:
        run_excel_writer(
            metrics_path=metrics_path, output_dir=output_dir, scope=args.excel_scope,
            node_command=args.node, writer_script=args.writer_script.resolve(),
            limit_hs=args.limit_hs,
            expected_hs_count=len({row.hs_code for row in history}),
        )

    summary = {
        "status": "complete",
        "raw_file": portable_path(raw_path),
        "manifest_file": portable_path(manifest_path),
        "history_file": portable_path(history_path),
        "metrics_file": portable_path(metrics_path),
        "output_directory": portable_path(output_dir),
        "hs_count": len({row.hs_code for row in history}),
        "history_row_count": len(history),
        "inserted_rows": inserted,
        "replaced_rows": replaced,
        "latest_month": latest_month,
        "excel_scope": None if args.skip_excel else args.excel_scope,
    }
    write_run_summary(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except NormalizationError as error:
        raise SystemExit(f"Normalization failed: {error}") from error
