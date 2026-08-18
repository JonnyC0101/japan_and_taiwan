"""Reconcile batched results to the official single-code table endpoint."""

from __future__ import annotations

import csv
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABLE_ENDPOINT = "https://publicinfo.trade.gov.tw/cuswebo/FSCE3010F/FSC3010P"


def number(value: str) -> float | None:
    text = value.replace(",", "").strip()
    return None if not text or text in {"--", "---"} else float(text)


def total_cells(flow: str, month: str, code: str, metric: str) -> list[str]:
    year, mon = month.split("-")
    payload = {
        "rdoIE_CODE": "I" if flow == "import" else "E",
        "ddlYearS": year, "ddlMonS": mon, "ddlYearE": year, "ddlMonE": mon,
        "chkVALUE_R": "false", "chkVALUE_P": "false", "chkVALUE_L": "false",
        "rdoMON": "2", "rdoCAC": "1", "ddlCONTINENTAL": "0", "ddlAREA": "018",
        "ddlCNTRY": "AF", "txtHS_CODE_S": code, "txtHS_CODE_E": "",
        "rdoType": "3" if metric == "quantity" else "4",
        "FrdoUnit": "0", "rdoUnit": "3" if metric == "quantity" else "2",
        "rdoUS100": "", "rdoReportCode": "All",
    }
    request = urllib.request.Request(
        TABLE_ENDPOINT, data=urllib.parse.urlencode(payload).encode("ascii"),
        headers={"User-Agent": "TaiwanTradeWorkflowValidation/1.0"}, method="POST",
    )
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                page = response.read().decode("utf-8-sig")
            break
        except OSError:
            if attempt == 5:
                raise
            time.sleep(2 ** (attempt - 1))
    match = re.search(r"<tr>\s*<td[^>]*>TOTAL</td>(.*?)</tr>", page, re.S)
    if not match:
        raise RuntimeError("TOTAL row not found in official table response")
    return [
        html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip()
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", match.group(1), re.S)
    ]


def raw_row(flow: str, month: str, code: str) -> dict[str, str]:
    path = ROOT / "data" / "raw" / flow / f"{flow}_{month}.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["ccc_code"] == code:
                return row
    raise KeyError(code)


def main() -> None:
    month = "2025-01"
    code = "84021200004"
    failures = []
    for flow in ("import", "export"):
        row = raw_row(flow, month, code)
        quantity_cells = total_cells(flow, month, code, "quantity")
        weight_cells = total_cells(flow, month, code, "weight")
        checks = {
            "value_usd_quantity_endpoint": (float(row["value_usd"]), number(quantity_cells[2])),
            "quantity": (float(row["quantity"]), number(quantity_cells[4])),
            "value_usd_weight_endpoint": (float(row["value_usd"]), number(weight_cells[2])),
            "weight_kg": (float(row["weight_kg"]), number(weight_cells[4])),
        }
        for name, (actual, official) in checks.items():
            if official is None or abs(actual - official) > 0.5:
                failures.append(f"{flow} {name}: batch={actual} official={official}")
        print(flow, checks)
    if failures:
        raise SystemExit("\n".join(failures))
    print("Single-code reconciliation passed for import and export.")


if __name__ == "__main__":
    main()
