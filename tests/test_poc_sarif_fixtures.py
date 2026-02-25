from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import cast


def _load_fixture_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "poc-sarif-fixtures.py"
    spec = importlib.util.spec_from_file_location("poc_sarif_fixtures", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPocSarifFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_fixture_module()

    def test_generate_category_split_has_expected_shape(self) -> None:
        sarif = cast(dict[str, object], self.mod.generate_category_split())

        self.assertEqual(sarif.get("version"), "2.1.0")
        runs = cast(list[object], sarif.get("runs", []))
        self.assertEqual(len(runs), 1)
        run = cast(dict[str, object], runs[0])

        results = cast(list[object], run.get("results", []))
        self.assertEqual(len(results), 20)

        driver = cast(dict[str, object], cast(dict[str, object], run["tool"])["driver"])
        rules = cast(list[object], driver.get("rules", []))
        rule_ids = {
            cast(dict[str, object], rule).get("id")
            for rule in rules
            if isinstance(rule, dict)
        }
        self.assertEqual(rule_ids, {"K7.P0", "K7.P1", "K7.P2", "K7.P3"})

    def test_generate_count_fixture_respects_requested_count(self) -> None:
        sarif = cast(dict[str, object], self.mod.generate_count_fixture(5001))
        runs = cast(list[object], sarif.get("runs", []))
        self.assertEqual(len(runs), 1)
        run = cast(dict[str, object], runs[0])

        results = cast(list[object], run.get("results", []))
        self.assertEqual(len(results), 5001)

        seen_rule_ids = {
            cast(dict[str, object], result).get("ruleId")
            for result in results
            if isinstance(result, dict)
        }
        self.assertEqual(seen_rule_ids, {"K7.P0", "K7.P1", "K7.P2", "K7.P3"})


if __name__ == "__main__":
    raise SystemExit(unittest.main())
