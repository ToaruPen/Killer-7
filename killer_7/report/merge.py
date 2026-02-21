from __future__ import annotations

from collections.abc import Mapping

from ..validate.evidence import recompute_review_status

_PRIORITY_ORDER = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
}


def _finding_sort_key(f: Mapping[str, object]) -> tuple[object, ...]:
    pr_obj = f.get("priority")
    pr = pr_obj if isinstance(pr_obj, str) else ""
    pr_rank = _PRIORITY_ORDER.get(pr, 99)

    repo_path = ""
    start_line = 0
    loc = f.get("code_location")
    if isinstance(loc, Mapping):
        p = loc.get("repo_relative_path")
        if isinstance(p, str):
            repo_path = p
        line_range = loc.get("line_range")
        if isinstance(line_range, Mapping):
            s = line_range.get("start")
            if isinstance(s, int):
                start_line = s

    title_obj = f.get("title")
    title = title_obj if isinstance(title_obj, str) else ""
    return (pr_rank, repo_path, start_line, title)


def merge_review_summary(
    *,
    scope_id: str,
    aspect_reviews: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Merge per-aspect review payloads into a single review-summary payload.

    This function is deliberately pure and deterministic (no I/O).
    """

    aspect_statuses: dict[str, str] = {}
    findings: list[Mapping[str, object]] = []
    questions_raw: list[str] = []
    explanations: list[str] = []

    for aspect in sorted(aspect_reviews.keys()):
        review = aspect_reviews[aspect]

        status_obj = review.get("status")
        if isinstance(status_obj, str) and status_obj:
            aspect_statuses[aspect] = status_obj

        f_obj = review.get("findings")
        if isinstance(f_obj, list):
            for item in f_obj:
                if isinstance(item, Mapping):
                    findings.append(item)

        q_obj = review.get("questions")
        if isinstance(q_obj, list):
            for item in q_obj:
                if isinstance(item, str) and item:
                    questions_raw.append(item)

        exp_obj = review.get("overall_explanation")
        if isinstance(exp_obj, str) and exp_obj.strip():
            explanations.append(f"[{aspect}] {exp_obj.strip()}")

    # De-duplicate questions while preserving order.
    questions: list[str] = []
    seen: set[str] = set()
    for q in questions_raw:
        if q in seen:
            continue
        seen.add(q)
        questions.append(q)

    findings_sorted = sorted(findings, key=_finding_sort_key)
    status = recompute_review_status(findings_sorted, questions)
    overall_explanation = "\n".join(explanations).strip() or "No issues."

    payload: dict[str, object] = {
        "schema_version": 3,
        "scope_id": scope_id,
        "status": status,
        "aspect_statuses": dict(aspect_statuses),
        "findings": list(findings_sorted),
        "questions": questions,
        "overall_explanation": overall_explanation,
    }
    return payload
