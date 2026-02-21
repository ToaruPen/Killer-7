from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, NoReturn

from ..artifacts import (
    atomic_write_json_secure,
    ensure_artifacts_dir,
    write_validation_error_json,
)
from ..aspect_id import normalize_aspect
from ..errors import BlockedError, ExecFailureError
from .run_one import ViewpointRunner, run_one_aspect

ASPECTS_V1: tuple[str, ...] = (
    "correctness",
    "readability",
    "testing",
    "test-audit",
    "security",
    "performance",
    "refactoring",
)


@dataclass(frozen=True)
class AspectOutcome:
    aspect: str
    ok: bool
    result_path: str
    error_kind: str
    error_message: str


def _write_aspect_error(
    *,
    out_dir: str,
    aspect: str,
    kind: str,
    message: str,
) -> str:
    aspects_dir = os.path.join(out_dir, "aspects")
    path = os.path.join(aspects_dir, f"{aspect}.error.json")
    atomic_write_json_secure(
        path,
        {
            "schema_version": 1,
            "aspect": aspect,
            "kind": kind,
            "message": message,
        },
    )
    return path


def _write_aspect_failure_artifact(
    *,
    out_dir: str,
    aspect: str,
    kind: str,
    message: str,
) -> str:
    target = f".ai-review/aspects/{aspect}.json"
    return write_validation_error_json(
        out_dir,
        filename=f"{aspect}.{kind}.error.json",
        kind=kind,
        message=message,
        target_path=target,
        errors=[],
        extra={"aspect": aspect},
    )


def _write_index(
    *,
    out_dir: str,
    scope_id: str,
    max_llm_calls: int,
    outcomes: list[AspectOutcome],
) -> str:
    aspects_dir = os.path.join(out_dir, "aspects")
    path = os.path.join(aspects_dir, "index.json")
    payload = {
        "schema_version": 1,
        "scope_id": scope_id,
        "max_llm_calls": max_llm_calls,
        "aspects": [
            {
                "aspect": o.aspect,
                "ok": o.ok,
                "result_path": os.path.relpath(o.result_path, out_dir)
                if o.result_path
                else "",
                "error_kind": o.error_kind,
                "error_message": o.error_message,
            }
            for o in outcomes
        ],
    }
    atomic_write_json_secure(path, payload)
    return path


def run_all_aspects(
    *,
    base_dir: str,
    scope_id: str,
    context_bundle: str,
    sot: str = "",
    aspects: tuple[str, ...] = ASPECTS_V1,
    max_llm_calls: int = 8,
    max_workers: int = 8,
    timeout_s: int | None = None,
    runner_factory: Callable[[], ViewpointRunner] | None = None,
    prompts_dir: str | None = None,
    runner_env_for_aspect: Callable[[str], dict[str, str] | None] | None = None,
    context_bundle_for_aspect: Callable[[str], str] | None = None,
    sot_for_aspect: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Run all aspects in parallel and write artifacts under `.ai-review/aspects/`.

    Success:
    - writes `.ai-review/aspects/<aspect>.json` for each aspect

    Failure:
    - writes `.ai-review/aspects/<aspect>.error.json` for failed aspects
    - writes `.ai-review/aspects/index.json` summarizing outcomes
    - raises BlockedError (exit code 1) if any aspect is blocked
    - raises ExecFailureError (exit code 2) if any aspect fails
    """

    if max_llm_calls < 1:
        raise ExecFailureError(
            f"Invalid max_llm_calls: {max_llm_calls!r} (must be >= 1)"
        )

    out_dir = ensure_artifacts_dir(base_dir)

    def fail_input(message: str) -> NoReturn:
        # Leave a machine-readable artifact even for configuration/input errors.
        _ = write_validation_error_json(
            out_dir,
            filename="aspects.input.error.json",
            kind="invalid_aspects",
            message=message,
            target_path=".ai-review/aspects/index.json",
            errors=[message],
        )
        raise ExecFailureError(message)

    aspect_list = tuple(aspects)
    if len(aspect_list) == 0:
        fail_input("No aspects to run")

    try:
        normalized_aspects = tuple(normalize_aspect(a) for a in aspect_list)
    except ExecFailureError as exc:
        fail_input(str(exc))
    if len(set(normalized_aspects)) != len(normalized_aspects):
        fail_input("Duplicate aspects after normalization")

    allowed = set(ASPECTS_V1)
    unknown = [a for a in normalized_aspects if a not in allowed]
    if unknown:
        fail_input(f"Unknown aspects: {', '.join(sorted(set(unknown)))}")

    if len(aspect_list) > max_llm_calls:
        fail_input(
            f"Too many aspects: {len(aspect_list)} (max_llm_calls={max_llm_calls})"
        )

    # Clear per-aspect error artifacts from previous runs.
    # `.ai-review/` is a stable directory and is not guaranteed to be empty.
    errors_dir = os.path.join(out_dir, "errors")
    os.makedirs(errors_dir, exist_ok=True)
    for a in normalized_aspects:
        for fname in (
            f"{a}.schema.error.json",
            f"{a}.exec_failure.error.json",
            f"{a}.unexpected.error.json",
        ):
            try:
                os.remove(os.path.join(errors_dir, fname))
            except FileNotFoundError:
                pass

    # Keep concurrency bounded and deterministic.
    workers = min(max_workers, max_llm_calls, len(normalized_aspects))
    if workers < 1:
        workers = 1

    outcomes: list[AspectOutcome] = []
    any_blocked = False
    any_failed = False

    def make_runner() -> ViewpointRunner:
        if runner_factory is None:
            from ..llm.opencode_runner import OpenCodeRunner

            return OpenCodeRunner.from_env()
        return runner_factory()

    def run_one(a: str) -> dict[str, object]:
        r = make_runner()
        env = runner_env_for_aspect(a) if runner_env_for_aspect else None
        aspect_context = (
            context_bundle_for_aspect(a)
            if context_bundle_for_aspect is not None
            else context_bundle
        )
        aspect_sot = sot_for_aspect(a) if sot_for_aspect is not None else sot
        return run_one_aspect(
            base_dir=base_dir,
            aspect=a,
            scope_id=scope_id,
            context_bundle=aspect_context,
            sot=aspect_sot,
            runner=r,
            timeout_s=timeout_s,
            prompts_dir=prompts_dir,
            runner_env=env,
        )

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, a): a for a in normalized_aspects}
        for fut in as_completed(futs):
            a = futs[fut]
            try:
                res = fut.result()
                p = str(res.get("aspect_result_path") or "")
                outcomes.append(
                    AspectOutcome(
                        aspect=a,
                        ok=True,
                        result_path=p,
                        error_kind="",
                        error_message="",
                    )
                )
            except BlockedError as exc:
                any_blocked = True
                err_path = _write_aspect_error(
                    out_dir=out_dir, aspect=a, kind="blocked", message=str(exc)
                )
                outcomes.append(
                    AspectOutcome(
                        aspect=a,
                        ok=False,
                        result_path=err_path,
                        error_kind="blocked",
                        error_message=str(exc),
                    )
                )
            except ExecFailureError as exc:
                any_failed = True
                err_path = _write_aspect_error(
                    out_dir=out_dir, aspect=a, kind="exec_failure", message=str(exc)
                )

                # If run_one_aspect already wrote a schema validation error artifact,
                # avoid duplicating errors artifacts for the same failure.
                schema_err = os.path.join(out_dir, "errors", f"{a}.schema.error.json")
                if not os.path.exists(schema_err):
                    _ = _write_aspect_failure_artifact(
                        out_dir=out_dir,
                        aspect=a,
                        kind="exec_failure",
                        message=str(exc),
                    )
                outcomes.append(
                    AspectOutcome(
                        aspect=a,
                        ok=False,
                        result_path=err_path,
                        error_kind="exec_failure",
                        error_message=str(exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                any_failed = True
                msg = f"Unexpected error: {type(exc).__name__}: {exc}"
                err_path = _write_aspect_error(
                    out_dir=out_dir, aspect=a, kind="unexpected", message=msg
                )
                _ = _write_aspect_failure_artifact(
                    out_dir=out_dir,
                    aspect=a,
                    kind="unexpected",
                    message=msg,
                )
                outcomes.append(
                    AspectOutcome(
                        aspect=a,
                        ok=False,
                        result_path=err_path,
                        error_kind="unexpected",
                        error_message=msg,
                    )
                )

    # Ensure a stable order for downstream processing.
    outcomes.sort(key=lambda x: x.aspect)
    index_path = _write_index(
        out_dir=out_dir,
        scope_id=scope_id,
        max_llm_calls=max_llm_calls,
        outcomes=outcomes,
    )

    if any_blocked:
        raise BlockedError(
            f"One or more aspects are blocked. See: {os.path.relpath(index_path, base_dir)}"
        )
    if any_failed:
        raise ExecFailureError(
            f"One or more aspects failed. See: {os.path.relpath(index_path, base_dir)}"
        )

    return {
        "scope_id": scope_id,
        "index_path": index_path,
        "aspects": [
            {
                "aspect": o.aspect,
                "ok": o.ok,
                "result_path": o.result_path,
                "error_kind": o.error_kind,
                "error_message": o.error_message,
            }
            for o in outcomes
        ],
    }
