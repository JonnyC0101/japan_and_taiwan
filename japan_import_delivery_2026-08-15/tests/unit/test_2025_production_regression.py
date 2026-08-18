from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from metrics import calculate_metrics  # noqa: E402
from normalizer import normalize_files  # noqa: E402


class Production2025RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = normalize_files(
            PROJECT_ROOT / "data" / "import_2025.csv",
            PROJECT_ROOT / "data" / "import_2025.manifest.json",
            PROJECT_ROOT / "data" / "reference" / "2025" / "import_totals_by_hs_code.csv",
        )
        cls.metrics = calculate_metrics(cls.rows)

    def test_complete_hs_month_grid(self) -> None:
        self.assertEqual(11460, len(self.rows))
        self.assertEqual(955, len({row.hs_code for row in self.rows}))
        self.assertEqual(180, sum(row.record_status == "zero_not_returned" for row in self.rows))

    def test_840140000_matches_attachment(self) -> None:
        rows = [row for row in self.metrics if row.hs_code == "840140000"]
        self.assertEqual(12, len(rows))
        self.assertEqual(
            [64, 586, 64, 70, 104, 64, 60, 46, 64, 30, 88, 72],
            [row.volume for row in rows],
        )
        self.assertEqual(
            [10324, 77724, 11028, 12127, 21990, 5935, 5519, 6208, 10481, 1052, 7469, 33950],
            [row.value_thousand_yen for row in rows],
        )
        self.assertAlmostEqual(471.5277777777778, rows[-1].asp_thousand_yen_per_unit2)
        self.assertEqual(42471, rows[-1].value_quarter_thousand_yen)


if __name__ == "__main__":
    unittest.main()
