from __future__ import annotations

import unittest

from killer_7.errors import ExecFailureError
from killer_7.llm.output_extract import extract_json_and_tool_uses_from_jsonl_lines


class TestOutputExtractToolTrace(unittest.TestCase):
    def test_extract_json_and_tool_uses_happy_path(self) -> None:
        lines = [
            "not json\n",
            '{"type": "step_start", "timestamp": 1, "sessionID": "ses_x", "part": {"type": "step-start"}}\n',
            (
                '{"type": "tool_use", "timestamp": 2, "sessionID": "ses_x", '
                '"part": {"type": "tool", "callID": "call_1", "tool": "bash", '
                '"state": {"status": "completed", "input": {"command": "git --no-pager diff --no-ext-diff"}, "output": "ok"}}}\n'
            ),
            '{"type": "text", "timestamp": 3, "sessionID": "ses_x", "part": {"type": "text", "text": "{\\"ok\\": true}"}}\n',
            '{"type": "step_finish", "timestamp": 4, "sessionID": "ses_x", "part": {"type": "step-finish"}}\n',
        ]

        payload, tool_uses = extract_json_and_tool_uses_from_jsonl_lines(lines)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0].get("type"), "tool_use")

        part = tool_uses[0].get("part")
        self.assertIsInstance(part, dict)
        if isinstance(part, dict):
            self.assertEqual(part.get("tool"), "bash")
            self.assertEqual(part.get("callID"), "call_1")

    def test_extract_json_and_tool_uses_invalid_jsonl_line_raises(self) -> None:
        lines = [
            '{"type": "text", "part": {"text": "{\\"ok\\": true}"}}\n',
            "{this is not valid json\n",
        ]
        with self.assertRaises(ExecFailureError):
            extract_json_and_tool_uses_from_jsonl_lines(lines)

    def test_extract_json_and_tool_uses_no_tool_uses_ok(self) -> None:
        lines = [
            '{"type": "text", "part": {"text": "{\\"n\\": 1}"}}\n',
        ]
        payload, tool_uses = extract_json_and_tool_uses_from_jsonl_lines(lines)
        self.assertEqual(payload, {"n": 1})
        self.assertEqual(tool_uses, [])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
