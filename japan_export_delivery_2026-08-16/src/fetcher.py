"""Fetch monthly Values by Commodity data from Japan Customs.

The module intentionally stops at the raw-data boundary: it downloads and
parses the values published by Japan Customs, but does not calculate metrics or
compare the result with the 2025 reference CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HS_FILE = PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "raw" / "latest_export.csv"
SEARCH_URL = "https://www.customs.go.jp/JCWSV04/servlet/JCWSV04"
PAGE_SIZE = 200
HS_CODE_PATTERN = re.compile(r"^\d{9}$")
DISPLAYED_HS_PATTERN = re.compile(r"^(\d{4})\.(\d{2})-(\d{3})$")
RESULT_COUNT_PATTERN = re.compile(
    r"results\s+of\s+retrieval\s+([\d,]+)\s+cases?", re.IGNORECASE
)


class FetchError(RuntimeError):
    """Raised when a response cannot be trusted as complete Customs data."""


@dataclass(frozen=True)
class RawRow:
    direction: str
    month: str
    hs_code: str
    unit1: str
    quantity1: int | None
    unit2: str
    quantity2: int | None
    value_thousand_yen: int | None
    ytd_quantity1: int | None
    ytd_quantity2: int | None
    ytd_value_thousand_yen: int | None
    fetched_at_utc: str


@dataclass(frozen=True)
class ParsedPage:
    direction: str
    month: str
    total_count: int
    rows: list[RawRow]


def normalize_hs_code(raw_value: str | None, context: str) -> str:
    """Return a validated nine-digit HS code."""
    value = (raw_value or "").strip().strip("'\"").strip()
    if not HS_CODE_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid HS code in {context}: {raw_value!r}. Expected nine digits."
        )
    return value


def load_hs_codes(path: Path) -> list[str]:
    """Load, validate, de-duplicate, and sort the requested HS codes."""
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or "HS Code" not in reader.fieldnames:
            raise ValueError(f"HS file must contain an 'HS Code' column: {path}")
        codes = [
            normalize_hs_code(row.get("HS Code"), f"row {row_number} of {path}")
            for row_number, row in enumerate(reader, start=2)
        ]

    if not codes:
        raise ValueError(f"HS file is empty: {path}")
    return sorted(set(codes))


def parse_month(value: str) -> date:
    """Parse YYYY-MM into a date set to the first day of that month."""
    try:
        parsed = datetime.strptime(value, "%Y-%m").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid month {value!r}; expected YYYY-MM."
        ) from error
    return parsed.replace(day=1)


def iter_months(start: date, end: date) -> Iterable[date]:
    """Yield inclusive calendar months."""
    if start > end:
        raise ValueError("Start month must not be later than end month.")
    current = start
    while current <= end:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def build_payload(
    month: date,
    direction: str,
    start_hs: str,
    end_hs: str | None = None,
) -> list[tuple[str, str]]:
    """Build the repeated-name form fields used by the Customs search form."""
    direction_code = {"export": "1", "import": "2"}[direction]
    is_range = end_hs is not None and end_hs != start_hs
    hs_codes = [start_hs, end_hs or ""] if is_range else [start_hs, ""]

    payload = [
        ("CW_SEARCHID", "JCCHT29S"),
        ("CW_JAPANKBN", "2"),
        ("CW_IMPKBN", direction_code),
        ("CW_CARGOKBN", ""),
        ("CW_SUMKBN", ""),
        ("CW_SPCODE", ""),
        ("CW_SPNAME", ""),
        ("CW_YMSORTKBN", ""),
        ("CW_SISUKBN", ""),
        ("CW_SENKIKBN", ""),
        ("CW_HKKBN", ""),
        ("CW_YMKBN", "1"),
        ("CW_KI", ""),
        ("CW_SYY", str(month.year)),
        ("CW_EYY", ""),
        ("CW_SMM", str(month.month)),
        ("CW_EMM", ""),
        ("CW_HSKBN", "3" if is_range else "2"),
    ]
    for index in range(10):
        payload.append(("CW_HSCODE", hs_codes[index] if index < len(hs_codes) else ""))
        payload.append(("CW_HSNAME", ""))
    payload.extend(
        [
            ("CW_KUNIKBN", ""),
            ("CW_KUNICODE", ""),
            ("CW_KUNINAME", ""),
            ("CW_ZMKBN", ""),
            ("CW_ZMCODE", ""),
            ("CW_ZMNAME", ""),
            ("CW_MEISAICNT", str(PAGE_SIZE)),
        ]
    )
    return payload


def create_session() -> requests.Session:
    """Create a polite, retrying HTTP session."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "conductordata/0.1 (academic validation; "
                "Japan Customs monthly trade statistics)"
            )
        }
    )
    return session


def parse_integer(raw_value: str, field: str, hs_code: str) -> int | None:
    """Parse an HTML numeric cell; an empty cell remains missing."""
    value = raw_value.replace(",", "").strip()
    if not value or value in {"-", "—"}:
        return None
    if not re.fullmatch(r"-?\d+", value):
        raise FetchError(f"Invalid {field} for HS {hs_code}: {raw_value!r}")
    return int(value)


def parse_displayed_hs(raw_value: str) -> str:
    """Convert the displayed 8401.40-000 form back to nine digits."""
    value = raw_value.replace("\xa0", " ").strip().split()[0]
    match = DISPLAYED_HS_PATTERN.fullmatch(value)
    if match is None:
        raise FetchError(f"Unexpected commodity code in result table: {raw_value!r}")
    return "".join(match.groups())


def _metadata(soup: BeautifulSoup) -> dict[str, str]:
    metadata: dict[str, str] = {}
    table = soup.select_one("table.auto")
    if table is None:
        return metadata
    for row in table.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index in range(0, len(cells) - 1, 2):
            if cells[index].name == "th":
                key = cells[index].get_text(" ", strip=True)
                value = cells[index + 1].get_text(" ", strip=True)
                metadata[key] = value
    return metadata


def parse_result_page(
    html: str,
    expected_direction: str,
    expected_month: date,
    fetched_at_utc: str,
) -> ParsedPage:
    """Parse and validate one Japan Customs result page."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_text = soup.get_text(" ", strip=True)
    normalized_month = expected_month.strftime("%Y-%m")
    if "Unpublished" in page_text and "not published yet" in page_text.lower():
        return ParsedPage(expected_direction.lower(), normalized_month, 0, [])
    if title == "ERROR" or "Requested search was not performed" in page_text:
        raise FetchError("Japan Customs returned an error page.")

    if "No Result" in page_text and "no information" in page_text.lower():
        return ParsedPage(expected_direction.lower(), normalized_month, 0, [])

    metadata = _metadata(soup)
    displayed_direction = metadata.get("Export and Import", "").lower()
    expected_display = expected_direction.lower()
    if displayed_direction != expected_display:
        raise FetchError(
            f"Direction mismatch: requested {expected_display}, "
            f"received {displayed_direction or 'unknown'}."
        )

    displayed_month = metadata.get("Year and month", "")
    expected_display_month = f"{expected_month.year}/{expected_month.month}"
    if displayed_month != expected_display_month:
        raise FetchError(
            f"Month mismatch: requested {expected_display_month}, "
            f"received {displayed_month or 'unknown'}."
        )

    count_match = RESULT_COUNT_PATTERN.search(page_text)
    if count_match is None:
        raise FetchError("Could not find the declared result count in the response.")
    total_count = int(count_match.group(1).replace(",", ""))

    value_table = soup.select_one("table.value")
    if value_table is None:
        raise FetchError("Could not find the Values by Commodity result table.")

    rows: list[RawRow] = []
    for table_row in value_table.select("tr"):
        cells = table_row.find_all("td", recursive=False)
        if not cells:
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        if values[0].strip().upper() == "TOTAL":
            continue
        if len(values) != 9:
            raise FetchError(
                f"Unexpected result row with {len(values)} cells; expected 9."
            )
        hs_code = parse_displayed_hs(values[0])
        rows.append(
            RawRow(
                direction=expected_display,
                month=normalized_month,
                hs_code=hs_code,
                unit1=values[1].strip(),
                quantity1=parse_integer(values[3], "quantity1", hs_code),
                unit2=values[2].strip(),
                quantity2=parse_integer(values[4], "quantity2", hs_code),
                value_thousand_yen=parse_integer(values[5], "value", hs_code),
                ytd_quantity1=parse_integer(values[6], "ytd_quantity1", hs_code),
                ytd_quantity2=parse_integer(values[7], "ytd_quantity2", hs_code),
                ytd_value_thousand_yen=parse_integer(
                    values[8], "ytd_value", hs_code
                ),
                fetched_at_utc=fetched_at_utc,
            )
        )

    if total_count <= PAGE_SIZE and len(rows) != total_count:
        raise FetchError(
            f"Page declared {total_count} rows but parser found {len(rows)}."
        )
    if len({row.hs_code for row in rows}) != len(rows):
        raise FetchError("The result page contains duplicate HS codes.")
    return ParsedPage(expected_display, normalized_month, total_count, rows)


class CustomsFetcher:
    """Fetch complete result ranges while avoiding stateful page navigation."""

    def __init__(
        self,
        session: requests.Session,
        delay_seconds: float = 1.0,
        timeout: tuple[float, float] = (10.0, 60.0),
    ) -> None:
        self.session = session
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.last_request_at: float | None = None
        self.request_count = 0
        self.excluded_non_target_codes: set[str] = set()

    def request_page(
        self,
        month: date,
        direction: str,
        start_hs: str,
        end_hs: str | None,
    ) -> ParsedPage:
        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay_seconds:
                time.sleep(self.delay_seconds - elapsed)
        payload = build_payload(month, direction, start_hs, end_hs)
        try:
            response = self.session.post(
                SEARCH_URL,
                data=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise FetchError(
                f"Request failed for {month:%Y-%m}, HS {start_hs}-{end_hs or start_hs}: "
                f"{error}"
            ) from error
        finally:
            self.last_request_at = time.monotonic()
            self.request_count += 1

        response.encoding = "utf-8"
        return parse_result_page(
            response.text,
            expected_direction=direction,
            expected_month=month,
            fetched_at_utc=datetime.now(UTC).isoformat(),
        )

    def fetch_code_group(
        self,
        month: date,
        direction: str,
        target_codes: Sequence[str],
    ) -> list[RawRow]:
        """Fetch one sorted code group, splitting it until each page is complete."""
        if not target_codes:
            return []
        start_hs = target_codes[0]
        end_hs = target_codes[-1] if len(target_codes) > 1 else None
        page = self.request_page(month, direction, start_hs, end_hs)

        if page.total_count > PAGE_SIZE:
            if len(target_codes) == 1:
                raise FetchError(
                    f"A single-code query for {start_hs} returned more than "
                    f"{PAGE_SIZE} rows and cannot be split safely."
                )
            midpoint = len(target_codes) // 2
            return self.fetch_code_group(
                month, direction, target_codes[:midpoint]
            ) + self.fetch_code_group(month, direction, target_codes[midpoint:])

        target_set = set(target_codes)
        selected: list[RawRow] = []
        for row in page.rows:
            if row.hs_code in target_set:
                selected.append(row)
            else:
                self.excluded_non_target_codes.add(row.hs_code)
        return selected


def group_codes_by_chapter(codes: Sequence[str]) -> list[list[str]]:
    """Start with small chapter groups before recursive range splitting."""
    groups: dict[str, list[str]] = {}
    for code in codes:
        groups.setdefault(code[:2], []).append(code)
    return [groups[key] for key in sorted(groups)]


def validate_rows(rows: Sequence[RawRow], target_codes: set[str]) -> None:
    """Validate the complete parsed dataset before writing it."""
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.hs_code not in target_codes:
            raise FetchError(f"Unexpected non-target HS code in output: {row.hs_code}")
        key = (row.month, row.hs_code)
        if key in seen:
            raise FetchError(f"Duplicate output row for {row.month}, HS {row.hs_code}.")
        seen.add(key)


def write_raw_csv(path: Path, rows: Sequence[RawRow]) -> None:
    """Atomically write raw rows, marking HS codes as text for Excel.

    CSV has no native column types.  A leading apostrophe follows the same
    convention as the official reference CSV and prevents spreadsheet programs
    from displaying a nine-digit HS code in scientific notation.  The in-memory
    value remains the canonical nine-digit string.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    fieldnames = list(RawRow.__dataclass_fields__)
    try:
        with temporary_path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(
                destination, fieldnames=fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            for row in rows:
                output_row = asdict(row)
                output_row["hs_code"] = f"'{row.hs_code}"
                writer.writerow(output_row)
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Atomically write a JSON record of what was and was not returned."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch monthly Values by Commodity data from Japan Customs."
    )
    parser.add_argument("--direction", choices=("export",), default="export")
    parser.add_argument("--start-month", type=parse_month, required=True)
    parser.add_argument("--end-month", type=parse_month)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--hs-code",
        action="append",
        help="One nine-digit HS code; repeat the option for multiple codes.",
    )
    source.add_argument("--hs-file", type=Path, default=DEFAULT_HS_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="JSON run manifest (default: beside output CSV).",
    )
    parser.add_argument("--delay", type=float, default=1.0)
    return parser.parse_args()


def fetch_to_files(
    *,
    direction: str,
    start_month: date,
    end_month: date,
    codes: Sequence[str],
    output_path: Path,
    manifest_path: Path,
    delay_seconds: float = 1.0,
) -> dict[str, object]:
    """Fetch a validated month range and atomically write CSV plus manifest."""
    months = list(iter_months(start_month, end_month))
    if not months:
        raise ValueError("No months were requested.")
    if delay_seconds < 0:
        raise ValueError("Delay must not be negative.")
    codes = sorted({normalize_hs_code(code, "fetch_to_files") for code in codes})
    if not codes:
        raise ValueError("No HS codes were requested.")

    print(
        f"Fetching {direction} data for {len(codes)} HS codes, "
        f"{months[0]:%Y-%m} to {months[-1]:%Y-%m}."
    )
    fetcher = CustomsFetcher(create_session(), delay_seconds=delay_seconds)
    all_rows: list[RawRow] = []
    returned_by_month: dict[str, set[str]] = {}
    groups = group_codes_by_chapter(codes)

    for month in months:
        month_key = month.strftime("%Y-%m")
        print(f"Fetching {month_key} ...", flush=True)
        month_rows: list[RawRow] = []
        for group in groups:
            month_rows.extend(fetcher.fetch_code_group(month, direction, group))
        returned_by_month[month_key] = {row.hs_code for row in month_rows}
        all_rows.extend(month_rows)
        print(f"  received {len(month_rows)} target rows", flush=True)

    all_rows.sort(key=lambda row: (row.month, row.hs_code))
    target_set = set(codes)
    validate_rows(all_rows, target_set)

    completed_at = datetime.now(UTC).isoformat()
    manifest: dict[str, object] = {
        "status": "complete",
        "source_url": SEARCH_URL,
        "direction": direction,
        "start_month": months[0].strftime("%Y-%m"),
        "end_month": months[-1].strftime("%Y-%m"),
        "requested_hs_count": len(codes),
        "written_row_count": len(all_rows),
        "http_request_count": fetcher.request_count,
        "excluded_non_target_hs_codes": sorted(fetcher.excluded_non_target_codes),
        "months": {
            month.strftime("%Y-%m"): {
                "returned_hs_count": len(returned_by_month[month.strftime("%Y-%m")]),
                "missing_hs_codes": sorted(
                    target_set - returned_by_month[month.strftime("%Y-%m")]
                ),
            }
            for month in months
        },
        "completed_at_utc": completed_at,
    }
    write_raw_csv(output_path, all_rows)
    write_manifest(manifest_path, manifest)
    print(f"Wrote {len(all_rows)} rows to {output_path}")
    print(f"Wrote run manifest to {manifest_path}")
    return manifest


def main() -> None:
    args = parse_args()
    end_month = args.end_month or args.start_month
    months = list(iter_months(args.start_month, end_month))
    if args.delay < 0:
        raise ValueError("Delay must not be negative.")

    if args.hs_code:
        codes = sorted(
            {
                normalize_hs_code(code, "--hs-code")
                for code in args.hs_code
            }
        )
    else:
        codes = load_hs_codes(args.hs_file.resolve())

    output_path = args.output.resolve()
    manifest_path = (
        args.manifest.resolve()
        if args.manifest
        else output_path.with_suffix(".manifest.json")
    )
    if output_path == manifest_path:
        raise ValueError("CSV output and manifest paths must be different.")

    fetch_to_files(
        direction=args.direction,
        start_month=months[0],
        end_month=months[-1],
        codes=codes,
        output_path=output_path,
        manifest_path=manifest_path,
        delay_seconds=args.delay,
    )


if __name__ == "__main__":
    main()
