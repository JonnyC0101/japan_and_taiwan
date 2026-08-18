from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fetcher import _payload  # noqa: E402
from reference import Commodity, make_batches  # noqa: E402


class CoreTests(unittest.TestCase):
    def test_import_and_export_are_separate_payloads(self) -> None:
        common = ("2026-07", "84011000007", "84012000005", "weight")
        self.assertEqual(_payload("import", *common)["rdoIE_CODE"], "I")
        self.assertEqual(_payload("export", *common)["rdoIE_CODE"], "E")

    def test_quantity_and_weight_modes(self) -> None:
        quantity = _payload("export", "2026-07", "84011000007", "84012000005", "quantity")
        weight = _payload("export", "2026-07", "84011000007", "84012000005", "weight")
        self.assertEqual((quantity["rdoType"], quantity["rdoUnit"]), ("3", "3"))
        self.assertEqual((weight["rdoType"], weight["rdoUnit"]), ("4", "2"))

    def test_batches_never_exceed_twenty(self) -> None:
        rows = [Commodity(str(index).zfill(11), "840000", "84000000", "", "", "", "KGM", "", "")
                for index in range(45)]
        batches = make_batches(rows, 20)
        self.assertEqual([len(batch) for batch in batches], [20, 20, 5])


if __name__ == "__main__":
    unittest.main()
