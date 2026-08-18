from __future__ import annotations

import csv
import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from metrics import calculate_metrics  # noqa: E402
from normalizer import normalize_files  # noqa: E402


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def official_2025() -> dict[tuple[str, str], tuple[int, int, int]]:
    reference_path = PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv"
    with reference_path.open("r", encoding="utf-8-sig", newline="") as source:
        targets = {row["HS Code"] for row in csv.DictReader(source)}
    output: dict[tuple[str, str], tuple[int, int, int]] = {}
    official_path = PROJECT_ROOT / "data" / "reference" / "2025" / "official_export_values_2025.csv"
    with official_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            code = re.sub(r"\D", "", row["HS"])
            if code not in targets:
                continue
            for number, label in enumerate(MONTHS, start=1):
                output[(f"2025-{number:02d}", code)] = (
                    int(row[f"Quantity1-{label}"] or 0),
                    int(row[f"Quantity2-{label}"] or 0),
                    int(row[f"Value-{label}"] or 0),
                )
    return output


class Production2025RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = normalize_files(
            PROJECT_ROOT / "data" / "export_2025.csv",
            PROJECT_ROOT / "data" / "export_2025.manifest.json",
            PROJECT_ROOT / "data" / "reference" / "export_hs_reference.csv",
        )
        cls.metrics = calculate_metrics(cls.rows)
        cls.official = official_2025()

    def test_complete_hs_month_grid(self) -> None:
        expected_hs = len({row.hs_code for row in self.rows})
        self.assertEqual(expected_hs * 12, len(self.rows))
        self.assertEqual(1029, expected_hs)
        self.assertLessEqual(len(self.official), len(self.rows))

    def test_every_quantity_and_value_matches_official_estat(self) -> None:
        mismatches = []
        for row in self.rows:
            expected_q1, expected_q2, expected_value = self.official.get(
                (row.month, row.hs_code), (0, 0, 0)
            )
            actual = (row.quantity1 or 0, row.quantity2 or 0, row.value_thousand_yen)
            if actual != (expected_q1, expected_q2, expected_value):
                mismatches.append((row.month, row.hs_code))
        self.assertEqual([], mismatches[:20])

    def test_metrics_cover_the_same_grid(self) -> None:
        self.assertEqual(len(self.rows), len(self.metrics))
        self.assertTrue(all(row.direction == "export" for row in self.metrics))


if __name__ == "__main__":
    unittest.main()
