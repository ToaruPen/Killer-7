from __future__ import annotations

from collections.abc import Mapping


def _finding_heading(f: Mapping[str, object]) -> str:
    pr = f.get("priority") if isinstance(f.get("priority"), str) else ""
    title = f.get("title") if isinstance(f.get("title"), str) else ""

    loc = f.get("code_location")
    loc_txt = ""
    if isinstance(loc, Mapping):
        path = loc.get("repo_relative_path")
        lr = loc.get("line_range")
        if isinstance(path, str) and isinstance(lr, Mapping):
            start = lr.get("start")
            end = lr.get("end")
            if isinstance(start, int) and isinstance(end, int):
                loc_txt = f" ({path}#L{start}-L{end})"

    pr_txt = f"[{pr}] " if pr else ""
    return f"- {pr_txt}{title}{loc_txt}".rstrip()


def format_review_summary_md(summary: Mapping[str, object]) -> str:
    status = summary.get("status")
    status_txt = status if isinstance(status, str) and status else "unknown"

    findings_obj = summary.get("findings")
    findings = findings_obj if isinstance(findings_obj, list) else []
    questions_obj = summary.get("questions")
    questions = questions_obj if isinstance(questions_obj, list) else []

    lines: list[str] = []
    lines.append("# Review Summary")
    lines.append("")
    lines.append(f"- Status: {status_txt}")
    lines.append("")

    lines.append("## Findings")
    if not findings:
        lines.append("")
        lines.append("(no findings)")
    else:
        p0_p1: list[Mapping[str, object]] = []
        p2_p3: list[Mapping[str, object]] = []
        other: list[Mapping[str, object]] = []
        for item in findings:
            if not isinstance(item, Mapping):
                continue
            pr = item.get("priority")
            if pr in ("P0", "P1"):
                p0_p1.append(item)
            elif pr in ("P2", "P3"):
                p2_p3.append(item)
            else:
                other.append(item)

        lines.append("")
        for item in p0_p1:
            lines.append(_finding_heading(item))

        if p2_p3:
            if p0_p1:
                lines.append("")
            lines.append("<details>")
            lines.append("<summary>P2/P3</summary>")
            lines.append("")
            for item in p2_p3:
                lines.append(_finding_heading(item))
            lines.append("")
            lines.append("</details>")

        for item in other:
            lines.append(_finding_heading(item))

    lines.append("")
    lines.append("## Questions")
    if not questions:
        lines.append("")
        lines.append("(no questions)")
    else:
        lines.append("")
        for q in questions:
            if isinstance(q, str) and q:
                lines.append(f"- {q}")

    return "\n".join(lines).rstrip("\n") + "\n"
