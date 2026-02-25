from __future__ import annotations

import unittest
from typing import Mapping, cast


class TestSarifExport(unittest.TestCase):
    def test_non_mapping_summary_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        with self.assertRaisesRegex(ValueError, "expected mapping at root"):
            invalid_summary = cast(object, None)
            review_summary_to_sarif(cast("Mapping[str, object]", invalid_summary))

    def test_empty_findings_generates_sarif(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-123@empty",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "No findings.",
        }

        sarif = review_summary_to_sarif(summary)
        self.assertIsInstance(sarif, dict)
        self.assertEqual(sarif.get("version"), "2.1.0")
        runs = cast(list[object], sarif.get("runs", []))
        self.assertTrue(isinstance(runs, list) and len(runs) == 1)
        self.assertIsInstance(runs[0], dict)
        run0 = cast(dict[str, object], runs[0])
        self.assertEqual(run0.get("results"), [])

    def test_converts_review_summary_to_sarif_with_locations(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-123@0123456789ab",
            "status": "Blocked",
            "findings": [
                {
                    "title": "Null guard missing",
                    "body": "Input can be None.",
                    "priority": "P0",
                    "verified": True,
                    "sources": ["src/app.py#L10-L12"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 10, "end": 12},
                    },
                },
                {
                    "title": "Nit",
                    "body": "Rename for readability.",
                    "priority": "P3",
                    "verified": False,
                    "original_priority": "P1",
                    "sources": ["docs/guide.md#L3-L3"],
                    "code_location": {
                        "repo_relative_path": "docs/guide.md",
                        "line_range": {"start": 3, "end": 3},
                    },
                },
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        sarif = review_summary_to_sarif(summary)

        self.assertEqual(sarif["version"], "2.1.0")
        self.assertIn("runs", sarif)
        runs = cast(list[object], sarif["runs"])
        self.assertTrue(isinstance(runs, list) and len(runs) == 1)
        self.assertIsInstance(runs[0], dict)

        run = cast(dict[str, object], runs[0])
        results = cast(list[object], run["results"])
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], dict)
        self.assertIsInstance(results[1], dict)

        first = cast(dict[str, object], results[0])
        self.assertEqual(first["level"], "error")
        self.assertEqual(first["ruleId"], "K7.P0")
        self.assertIsInstance(first["locations"], list)
        locations = cast(list[object], first["locations"])
        loc0_holder = locations[0]
        self.assertIsInstance(loc0_holder, dict)
        loc0 = cast(dict[str, object], loc0_holder)["physicalLocation"]
        self.assertIsInstance(loc0, dict)
        loc0_map = cast(dict[str, object], loc0)
        artifact = cast(dict[str, object], loc0_map["artifactLocation"])
        region = cast(dict[str, object], loc0_map["region"])
        self.assertEqual(artifact["uri"], "src/app.py")
        self.assertEqual(region["startLine"], 10)
        self.assertEqual(region["endLine"], 12)

        second = cast(dict[str, object], results[1])
        self.assertEqual(second["level"], "note")
        self.assertEqual(second["ruleId"], "K7.P3")
        props = cast(dict[str, object], second.get("properties", {}))
        self.assertEqual(props.get("priority"), "P3")
        self.assertEqual(props.get("original_priority"), "P1")
        self.assertEqual(props.get("verified"), False)

    def test_result_contains_stable_partial_fingerprint(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        sarif = review_summary_to_sarif(summary)
        runs = cast(list[object], sarif["runs"])
        self.assertIsInstance(runs, list)
        self.assertIsInstance(runs[0], dict)
        run = cast(dict[str, object], runs[0])
        results = cast(list[object], run["results"])
        self.assertIsInstance(results, list)
        self.assertIsInstance(results[0], dict)
        result = cast(dict[str, object], results[0])
        pfp = cast(dict[str, object], result.get("partialFingerprints", {}))
        self.assertIsInstance(pfp, dict)

        self.assertIn("k7/finding", pfp)
        self.assertTrue(str(pfp["k7/finding"]).startswith("k7f1:"))

    def test_missing_code_location_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing code_location"):
            review_summary_to_sarif(summary)

    def test_invalid_line_range_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 0, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "line_range.start must be int >= 1"):
            review_summary_to_sarif(summary)

    def test_missing_line_range_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing line_range"):
            review_summary_to_sarif(summary)

    def test_missing_repo_relative_path_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing repo_relative_path"):
            review_summary_to_sarif(summary)

    def test_line_range_end_before_start_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 5, "end": 3},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "line_range.end must be int >= start"):
            review_summary_to_sarif(summary)

    def test_line_range_start_bool_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": True, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "line_range.start must be int >= 1"):
            review_summary_to_sarif(summary)

    def test_line_range_end_bool_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": False},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "line_range.end must be int >= start"):
            review_summary_to_sarif(summary)

    def test_missing_priority_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-123@abcdef",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing required priority"):
            review_summary_to_sarif(summary)

    def test_missing_title_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-123@abcdef",
            "status": "Approved",
            "findings": [
                {
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing title"):
            review_summary_to_sarif(summary)

    def test_unknown_priority_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-123@abcdef",
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P9",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "unsupported value 'P9'"):
            review_summary_to_sarif(summary)

    def test_missing_scope_id_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "status": "Approved",
            "findings": [
                {
                    "title": "A",
                    "body": "B",
                    "priority": "P1",
                    "sources": ["a.py#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "a.py",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "missing required scope_id"):
            review_summary_to_sarif(summary)

    def test_findings_not_array_fails_fast(self) -> None:
        from killer_7.report.sarif_export import review_summary_to_sarif

        summary = {
            "schema_version": 3,
            "scope_id": "s",
            "status": "Approved",
            "findings": "not-a-list",
            "questions": [],
            "overall_explanation": "ok",
        }

        with self.assertRaisesRegex(ValueError, "raw_findings must be a list"):
            review_summary_to_sarif(summary)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
