from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from data_model import NormalizedRow, read_normalized_csv  # noqa: E402
from history_store import merge_history  # noqa: E402
from metrics import calculate_metrics  # noqa: E402
from normalizer import NormalizationError, normalize_files  # noqa: E402
from fetcher import parse_result_page  # noqa: E402


class ProductionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_csv(self, path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_normalizer_materializes_confirmed_omitted_zero(self) -> None:
        reference = self.root / "reference.csv"
        self.write_csv(
            reference, ["HS", "Unit1", "Unit2"],
            [
                {"HS": "'840140000", "Unit1": "", "Unit2": "KG"},
                {"HS": "'840211000", "Unit1": "NO", "Unit2": "KG"},
            ],
        )
        raw = self.root / "raw.csv"
        raw_fields = [
            "direction", "month", "hs_code", "unit1", "quantity1", "unit2", "quantity2",
            "value_thousand_yen", "ytd_quantity1", "ytd_quantity2", "ytd_value_thousand_yen",
            "fetched_at_utc",
        ]
        self.write_csv(
            raw, raw_fields,
            [{
                "direction": "import", "month": "2025-01", "hs_code": "'840140000",
                "unit1": "", "quantity1": "", "unit2": "KG", "quantity2": 64,
                "value_thousand_yen": 10324, "ytd_quantity1": "", "ytd_quantity2": 64,
                "ytd_value_thousand_yen": 10324,
                "fetched_at_utc": "2026-08-12T00:00:00+00:00",
            }],
        )
        manifest = self.root / "raw.manifest.json"
        manifest.write_text(json.dumps({
            "status": "complete", "direction": "import", "written_row_count": 1,
            "completed_at_utc": "2026-08-12T00:00:00+00:00",
            "months": {"2025-01": {"returned_hs_count": 1, "missing_hs_codes": ["840211000"]}},
        }), encoding="utf-8")
        rows = normalize_files(raw, manifest, reference)
        self.assertEqual(2, len(rows))
        zero = next(row for row in rows if row.hs_code == "840211000")
        self.assertEqual("zero_not_returned", zero.record_status)
        self.assertEqual(0, zero.quantity1)
        self.assertEqual(0, zero.quantity2)
        self.assertEqual(0, zero.value_thousand_yen)

    def test_normalizer_rejects_unpublished_month(self) -> None:
        reference = self.root / "reference.csv"
        self.write_csv(reference, ["HS", "Unit1", "Unit2"], [{"HS": "840140000", "Unit1": "", "Unit2": "KG"}])
        raw = self.root / "raw.csv"
        self.write_csv(raw, [
            "direction", "month", "hs_code", "unit1", "quantity1", "unit2", "quantity2",
            "value_thousand_yen", "ytd_quantity1", "ytd_quantity2", "ytd_value_thousand_yen", "fetched_at_utc",
        ], [])
        manifest = self.root / "raw.manifest.json"
        manifest.write_text(json.dumps({
            "status": "complete", "direction": "import", "months": {
                "2026-07": {"returned_hs_count": 0, "missing_hs_codes": ["840140000"]}
            },
        }), encoding="utf-8")
        with self.assertRaises(NormalizationError):
            normalize_files(raw, manifest, reference)

    def test_history_merge_is_idempotent_and_replaces_revisions(self) -> None:
        history = self.root / "history.csv"
        original = NormalizedRow(
            "import", "2025-01", "840140000", "", None, "KG", 64, 10324,
            None, 64, 10324, "first", "reported",
        )
        merged, inserted, replaced = merge_history(history, [original])
        self.assertEqual((1, 0), (inserted, replaced))
        revised = NormalizedRow(
            "import", "2025-01", "840140000", "", None, "KG", 65, 10400,
            None, 65, 10400, "second", "reported",
        )
        merged, inserted, replaced = merge_history(history, [revised])
        self.assertEqual((0, 1), (inserted, replaced))
        self.assertEqual(65, read_normalized_csv(history)[0].quantity2)

    def test_metrics_match_attachment_definitions(self) -> None:
        rows = []
        values = [(64, 10324), (586, 77724), (64, 11028)]
        for index, (quantity, value) in enumerate(values, start=1):
            rows.append(NormalizedRow(
                "import", f"2025-{index:02d}", "840140000", "", None, "KG", quantity,
                value, None, None, None, "test", "reported",
            ))
        metrics = calculate_metrics(rows)
        self.assertAlmostEqual(161.3125, metrics[0].asp_thousand_yen_per_unit2)
        self.assertAlmostEqual(132.6348122866894, metrics[1].asp_thousand_yen_per_unit2)
        self.assertAlmostEqual(155.4199374288965, metrics[2].asp_3mma)
        self.assertEqual(99076, metrics[2].value_quarter_thousand_yen)

    def test_unpublished_customs_page_is_a_clean_empty_result(self) -> None:
        parsed = parse_result_page(
            "<html><head><title>Trade Statistics</title></head>"
            "<body><h1>No Result</h1><p>There is no information.</p></body></html>",
            expected_direction="import",
            expected_month=datetime(2026, 7, 1, tzinfo=UTC).date(),
            fetched_at_utc="test",
        )
        self.assertEqual("import", parsed.direction)
        self.assertEqual("2026-07", parsed.month)
        self.assertEqual(0, parsed.total_count)
        self.assertEqual([], parsed.rows)

    def test_explicit_unpublished_customs_page_is_a_clean_empty_result(self) -> None:
        parsed = parse_result_page(
            "<html><body><h1>Unpublished</h1><p>Requested Search was not performed. "
            "The requested statistics years is not published yet.</p></body></html>",
            expected_direction="import",
            expected_month=datetime(2026, 7, 1, tzinfo=UTC).date(),
            fetched_at_utc="test",
        )
        self.assertEqual("2026-07", parsed.month)
        self.assertEqual([], parsed.rows)


if __name__ == "__main__":
    unittest.main()
