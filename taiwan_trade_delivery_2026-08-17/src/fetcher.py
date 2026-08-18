"""Fetch monthly Taiwan import/export quantity, weight, and USD value data."""

from __future__ import annotations

import csv
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from reference import Commodity, make_batches


QUERY_PAGE = "https://publicinfo.trade.gov.tw/cuswebo/FSCE3000C?table=FSCE3020F"
DATA_ENDPOINT = "https://publicinfo.trade.gov.tw/cuswebo/FSCE3020F/GetData"
FLOW_CODES = {"import": "I", "export": "E"}
RAW_FIELDS = (
    "reporter", "flow", "month", "ccc_code", "hs6", "hs8",
    "commodity_name_zh", "commodity_name_en", "quantity_unit", "quantity",
    "weight_kg", "value_usd", "record_status", "fetched_at_utc", "source_url",
)


@dataclass(frozen=True)
class RawRecord:
    reporter: str
    flow: str
    month: str
    ccc_code: str
    hs6: str
    hs8: str
    commodity_name_zh: str
    commodity_name_en: str
    quantity_unit: str
    quantity: float | None
    weight_kg: float | None
    value_usd: float | None
    record_status: str
    fetched_at_utc: str
    source_url: str


class FetchError(RuntimeError):
    pass


_rate_lock = threading.Lock()
_last_request = 0.0


def _polite_wait(min_interval: float) -> None:
    global _last_request
    if min_interval <= 0:
        return
    with _rate_lock:
        elapsed = time.monotonic() - _last_request
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request = time.monotonic()


def _post_json(payload: dict[str, str], retries: int, min_interval: float) -> dict[str, object]:
    encoded = urllib.parse.urlencode(payload).encode("ascii")
    for attempt in range(1, retries + 1):
        _polite_wait(min_interval)
        request = urllib.request.Request(
            DATA_ENDPOINT,
            data=encoded,
            headers={
                "User-Agent": "TaiwanTradeWorkflow/1.0 (+official-statistics-research)",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": QUERY_PAGE,
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8-sig")
            result = json.loads(raw)
            if not isinstance(result, dict) or "Month" not in result:
                raise FetchError(f"Unexpected response: {raw[:300]}")
            return result
        except (OSError, urllib.error.URLError, json.JSONDecodeError, FetchError) as error:
            if attempt == retries:
                raise FetchError(f"Official endpoint failed after {retries} attempts: {error}") from error
            time.sleep(min(20.0, 1.5 * 2 ** (attempt - 1)) + random.random())
    raise AssertionError("unreachable")


def _payload(flow: str, month: str, start_code: str, end_code: str, metric: str) -> dict[str, str]:
    if flow not in FLOW_CODES:
        raise ValueError(f"Unsupported flow: {flow}")
    if metric not in {"quantity", "weight"}:
        raise ValueError(f"Unsupported metric: {metric}")
    year, month_number = month.split("-")
    return {
        "ddlYearS": year, "ddlYearE": year,
        "ddlMonS": month_number, "ddlMonE": month_number,
        "rdoIE_CODE": FLOW_CODES[flow], "rdoCAC": "1", "ddlCNTRY": "AF",
        "ddlCONTINENTAL": "0", "ddlAREA": "018", "rdoHsNum": "0",
        "txtHS_CODE_S": start_code, "txtHS_CODE_E": end_code,
        "rdoType": "3" if metric == "quantity" else "4",
        "rdoMON": "1", "ReportType": "Report", "chkVALUE_P": "false",
        "chkVALUE_R": "true", "chkVALUE_L": "false",
        "rdoUnit": "3" if metric == "quantity" else "2", "rdoUS100": "",
        "rdoRank": "1000", "ddlTop": "20", "rdoReportCode": "All", "Hide": "0",
    }


def _number(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text in {"---", "--"}:
        return None
    return float(text)


def fetch_batch(
    *, flow: str, month: str, batch: list[Commodity], metric: str,
    retries: int = 5, min_interval: float = 0.03,
) -> tuple[dict[str, tuple[float | None, float | None]], list[dict[str, object]]]:
    result = _post_json(
        _payload(flow, month, batch[0].ccc_code, batch[-1].ccc_code, metric),
        retries=retries, min_interval=min_interval,
    )
    codes = list(result.get("Month") or [])
    amounts = list(result.get("Expences") or [])
    secondary = list(result.get("Income") or [])
    parsed: dict[str, tuple[float | None, float | None]] = {}
    hidden: list[dict[str, object]] = []
    allowed = {row.ccc_code for row in batch}
    for index in range(max(len(codes), len(amounts), len(secondary))):
        code = str(codes[index] if index < len(codes) else "").strip()
        amount = _number(amounts[index] if index < len(amounts) else None)
        metric_value = _number(secondary[index] if index < len(secondary) else None)
        if re.fullmatch(r"\d{11}", code) and code in allowed:
            parsed[code] = (amount, metric_value)
        elif amount not in (None, 0) or metric_value not in (None, 0):
            hidden.append({"code_label": code, "amount": amount, "secondary": metric_value})
    return parsed, hidden


def fetch_month(
    *, flow: str, month: str, commodities: list[Commodity], concurrency: int = 12,
    batch_size: int = 20, retries: int = 5, min_interval: float = 0.03,
    limit_batches: int | None = None,
) -> tuple[list[RawRecord], dict[str, object]]:
    batches = make_batches(commodities, batch_size)
    if limit_batches is not None:
        batches = batches[:limit_batches]
        commodities = [item for batch in batches for item in batch]
    jobs = [(index, batch, metric) for index, batch in enumerate(batches)
            for metric in ("quantity", "weight")]
    results: dict[tuple[int, str], dict[str, tuple[float | None, float | None]]] = {}
    hidden_by_batch: dict[int, list[dict[str, object]]] = {}
    failed_jobs: list[tuple[int, str, Exception]] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                fetch_batch, flow=flow, month=month, batch=batch, metric=metric,
                retries=retries, min_interval=min_interval,
            ): (index, metric)
            for index, batch, metric in jobs
        }
        for future in as_completed(futures):
            index, metric = futures[future]
            try:
                parsed, hidden = future.result()
                results[(index, metric)] = parsed
                if hidden:
                    hidden_by_batch.setdefault(index, []).extend(
                        [{"metric": metric, **item} for item in hidden]
                    )
            except Exception as error:
                failed_jobs.append((index, metric, error))
            completed += 1
            if completed % 20 == 0 or completed == len(jobs):
                print(f"  completed {completed}/{len(jobs)} official batch requests", flush=True)
    if failed_jobs:
        print(f"  retrying {len(failed_jobs)} failed batch requests serially", flush=True)
        remaining: list[str] = []
        for index, metric, original_error in failed_jobs:
            try:
                parsed, hidden = fetch_batch(
                    flow=flow, month=month, batch=batches[index], metric=metric,
                    retries=max(retries, 8), min_interval=max(min_interval, 0.1),
                )
                results[(index, metric)] = parsed
                if hidden:
                    hidden_by_batch.setdefault(index, []).extend(
                        [{"metric": metric, **item} for item in hidden]
                    )
                print(f"  recovered batch={index} metric={metric}", flush=True)
            except Exception as error:
                remaining.append(
                    f"batch={index} metric={metric}: first={original_error}; final={error}"
                )
        if remaining:
            raise FetchError("; ".join(remaining[:10]))

    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[RawRecord] = []
    amount_mismatches = 0
    for batch_index, batch in enumerate(batches):
        quantity_rows = results[(batch_index, "quantity")]
        weight_rows = results[(batch_index, "weight")]
        batch_hidden = bool(hidden_by_batch.get(batch_index))
        for item in batch:
            q_amount, quantity = quantity_rows.get(item.ccc_code, (None, None))
            w_amount, weight = weight_rows.get(item.ccc_code, (None, None))
            if q_amount is not None and w_amount is not None and abs(q_amount - w_amount) > 0.5:
                amount_mismatches += 1
            amount = w_amount if w_amount is not None else q_amount
            returned = item.ccc_code in quantity_rows or item.ccc_code in weight_rows
            if returned:
                status = "reported"
            elif batch_hidden:
                status = "not_returned_batch_has_protected_row"
            else:
                status = "zero_no_return"
                amount, quantity, weight = 0.0, 0.0 if item.quantity_unit else None, 0.0
            records.append(RawRecord(
                reporter="Taiwan", flow=flow, month=month, ccc_code=item.ccc_code,
                hs6=item.hs6, hs8=item.hs8,
                commodity_name_zh=item.commodity_name_zh,
                commodity_name_en=item.commodity_name_en,
                quantity_unit=item.quantity_unit, quantity=quantity,
                weight_kg=weight, value_usd=amount, record_status=status,
                fetched_at_utc=fetched_at, source_url=DATA_ENDPOINT,
            ))
    manifest = {
        "reporter": "Taiwan", "flow": flow, "month": month,
        "source_page": QUERY_PAGE, "source_endpoint": DATA_ENDPOINT,
        "trade_scope": "includes re-imports/re-exports (rdoReportCode=All)",
        "ccc_count": len(commodities), "batch_count": len(batches),
        "request_count": len(jobs),
        "reported_count": sum(row.record_status == "reported" for row in records),
        "zero_count": sum(row.record_status == "zero_no_return" for row in records),
        "protected_batch_count": len(hidden_by_batch),
        "hidden_rows": hidden_by_batch,
        "amount_mismatch_count": amount_mismatches,
        "fetched_at_utc": fetched_at,
    }
    return records, manifest


def write_raw(records: list[RawRecord], csv_path: Path, manifest: dict[str, object]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
    csv_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def latest_published_month(retries: int = 4) -> str:
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                QUERY_PAGE, headers={"User-Agent": "TaiwanTradeWorkflow/1.0"}
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                html = response.read().decode("utf-8-sig")
            year_block = re.search(r'id="ddlYearE"[^>]*>\s*<option value="(\d{4})"', html)
            month_block = re.search(r'id="ddlMonE"[^>]*>\s*<option value="(\d{2})"', html)
            if year_block and month_block:
                return f"{year_block.group(1)}-{month_block.group(1)}"
            raise FetchError("Latest period selectors were not found")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")
