#!/usr/bin/env python3
"""anchor-gate — deterministic stage acceptance gates for multi-agent pipelines.

A stage is accepted only when every anchor declared in the pipeline spec is
satisfied by an observable artifact: a file that exists, a hash that matches, a
gate command that exits 0. No model sits in the acceptance path, so "the agent
said it is done" is never evidence.

Exit codes are stable and documented in README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

EXIT_PROCEED = 0
EXIT_ANCHOR_FAILED = 1
EXIT_CONFIG = 2
EXIT_PARK = 3
EXIT_HALT = 4
EXIT_BOUNCE = 5

ACTION_EXIT = {
    "proceed": EXIT_PROCEED,
    "anchor_failed": EXIT_ANCHOR_FAILED,
    "park": EXIT_PARK,
    "halt": EXIT_HALT,
    "bounce": EXIT_BOUNCE,
}

KINDS = ("nonempty", "file", "sha256", "true", "equals", "cmd")

ATTEMPTS_FIELD = "stageAttempts"
ATTEMPTS_STAGE_FIELD = "attemptsStage"


class SpecError(Exception):
    """The pipeline spec, its state file or a path in it cannot be used."""


def load_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError(f"{what} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(f"{what} {path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{what} {path}: expected a JSON object")
    return data


def validate_spec(spec: dict) -> None:
    stages = spec.get("stages")
    if not isinstance(stages, dict) or not stages:
        raise SpecError("spec.stages must be a non-empty object")
    for name, stage in stages.items():
        if not isinstance(stage, dict):
            raise SpecError(f"spec.stages.{name} must be an object")
        anchors = stage.get("anchors", [])
        if not isinstance(anchors, list):
            raise SpecError(f"spec.stages.{name}.anchors must be a list")
        for index, anchor in enumerate(anchors):
            where = f"spec.stages.{name}.anchors[{index}]"
            if not isinstance(anchor, dict):
                raise SpecError(f"{where} must be an object")
            kind = anchor.get("kind")
            if kind not in KINDS:
                raise SpecError(f"{where}.kind must be one of {', '.join(KINDS)}")
            if kind != "cmd" and not anchor.get("field"):
                raise SpecError(f"{where}.field is required for kind {kind}")
            if kind == "sha256" and not (anchor.get("of") or anchor.get("field")):
                raise SpecError(f"{where} needs a source file field")
            if kind == "equals" and "value" not in anchor:
                raise SpecError(f"{where}.value is required for kind equals")
            if kind == "cmd" and not isinstance(anchor.get("cmd"), list):
                raise SpecError(f"{where}.cmd must be an argv list, not a shell string")
    max_attempts = spec.get("maxAttempts", 2)
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise SpecError("spec.maxAttempts must be an integer >= 1")
    bounce = spec.get("bounceSignal")
    if bounce is not None:
        if not isinstance(bounce, dict) or not bounce.get("field"):
            raise SpecError("spec.bounceSignal needs a field")
        target = bounce.get("to")
        if target is not None and target not in stages:
            raise SpecError(f"spec.bounceSignal.to `{target}` is not a declared stage")


def resolve(value: object, base: Path) -> Path:
    """Relative paths resolve against the spec's directory, so specs stay portable."""
    text = os.path.expandvars(str(value))
    path = Path(text).expanduser()
    return path if path.is_absolute() else (base / path)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_anchor(anchor: dict, state: dict, base: Path) -> dict:
    kind = anchor["kind"]
    field = anchor.get("field", "")
    raw = state.get(field)
    result = {"kind": kind, "field": field, "ok": False, "detail": ""}

    def fail(detail: str) -> dict:
        result["detail"] = detail
        return result

    if kind == "nonempty":
        ok = raw not in (None, "", [], {})
        result["ok"] = ok
        result["detail"] = "present" if ok else f"`{field}` is empty"

    elif kind == "file":
        if not raw:
            return fail(f"`{field}` is empty")
        path = resolve(raw, base)
        if not path.is_file():
            return fail(f"missing file {path}")
        size = path.stat().st_size
        minimum = int(anchor.get("minBytes", 0))
        result["ok"] = size >= minimum
        result["detail"] = f"{size} bytes" + ("" if result["ok"] else f" < minBytes {minimum}")

    elif kind == "sha256":
        source = state.get(anchor.get("of") or field)
        if not source:
            return fail(f"`{anchor.get('of') or field}` is empty")
        path = resolve(source, base)
        if not path.is_file():
            return fail(f"missing file {path}")
        actual = sha256_of(path)
        expected = str(raw or "")
        if not expected:
            return fail(f"`{field}` is empty")
        if anchor.get("prefix"):
            ok = actual.startswith(expected)
        else:
            ok = actual == expected
        result["ok"] = ok
        result["detail"] = f"actual {actual[:16]}" + ("" if ok else f" != expected {expected[:16]}")

    elif kind == "true":
        result["ok"] = raw is True
        result["detail"] = f"`{field}` is {raw!r}"

    elif kind == "equals":
        result["ok"] = raw == anchor["value"]
        result["detail"] = f"`{field}` is {raw!r}"

    elif kind == "cmd":
        argv = anchor["cmd"]
        try:
            completed = subprocess.run(
                argv,
                cwd=str(base),
                capture_output=True,
                text=True,
                timeout=anchor.get("timeout", 120),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return fail(f"command failed to run: {exc}")
        expected_code = int(anchor.get("expect", 0))
        result["ok"] = completed.returncode == expected_code
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-1:]
        result["detail"] = f"exit {completed.returncode}" + (f" ({tail[0][:120]})" if tail else "")

    return result


def verify(state: dict, spec: dict, base: Path) -> dict:
    stage_name = state.get("stage")
    stages = spec["stages"]
    if stage_name not in stages:
        raise SpecError(f"state.stage `{stage_name}` is not declared in the spec")
    stage = stages[stage_name]
    checks = [check_anchor(anchor, state, base) for anchor in stage.get("anchors", [])]
    return {
        "stage": stage_name,
        "anchorOk": all(check["ok"] for check in checks),
        "checks": checks,
    }


def current_attempts(state: dict, stage_name: str) -> int:
    """Attempts are per stage: a stage change starts a fresh budget."""
    if state.get(ATTEMPTS_STAGE_FIELD) != stage_name:
        return 0
    try:
        return max(0, int(state.get(ATTEMPTS_FIELD) or 0))
    except (TypeError, ValueError):
        return 0


def govern(state: dict, spec: dict, base: Path) -> tuple[dict, dict]:
    """Return (verdict, next_state). next_state is what to persist."""
    stage_name = state.get("stage")
    next_state = dict(state)

    if stage_name in spec.get("haltStages", []):
        # Terminal stages declare no anchors, so nothing is verified there.
        return (
            {
                "action": "halt",
                "reason": f"stage `{stage_name}` is terminal",
                "stage": stage_name,
                "attempts": current_attempts(state, stage_name),
                "maxAttempts": int(spec.get("maxAttempts", 2)),
                "anchorOk": True,
                "failedChecks": [],
            },
            next_state,
        )

    report = verify(state, spec, base)
    attempts = current_attempts(state, stage_name)
    max_attempts = int(spec.get("maxAttempts", 2))

    def verdict(action: str, reason: str) -> tuple[dict, dict]:
        return (
            {
                "action": action,
                "reason": reason,
                "stage": stage_name,
                "attempts": attempts,
                "maxAttempts": max_attempts,
                "anchorOk": report["anchorOk"],
                "failedChecks": [c for c in report["checks"] if not c["ok"]],
            },
            next_state,
        )

    bounce = spec.get("bounceSignal")
    if bounce and state.get(bounce["field"]) == bounce.get("value"):
        target = bounce.get("to") or next(iter(spec["stages"]))
        next_state["stage"] = target
        next_state[ATTEMPTS_FIELD] = 0
        next_state[ATTEMPTS_STAGE_FIELD] = target
        next_state["backwardBounces"] = int(state.get("backwardBounces") or 0) + 1
        return verdict("bounce", f"`{bounce['field']}` is {bounce.get('value')!r}, back to `{target}`")

    if report["anchorOk"]:
        next_state[ATTEMPTS_FIELD] = 0
        next_state[ATTEMPTS_STAGE_FIELD] = stage_name
        return verdict("proceed", "every anchor satisfied")

    attempts += 1
    next_state[ATTEMPTS_FIELD] = attempts
    next_state[ATTEMPTS_STAGE_FIELD] = stage_name
    if attempts >= max_attempts:
        next_state["stage"] = spec.get("parkStage", "PARKED")
        return verdict("park", f"anchor failed {attempts} of {max_attempts} attempts")
    return verdict("anchor_failed", f"anchor failed, attempt {attempts} of {max_attempts}")


def write_state(path: Path, state: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchor-gate",
        description="Deterministic acceptance gates and attempt budgets for agent pipelines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, text in (
        ("verify", "Check the anchors of the current stage; exit 0 only if all pass."),
        ("govern", "Verify, then decide proceed / anchor_failed / park / halt / bounce."),
    ):
        cmd = sub.add_parser(name, help=text, description=text)
        cmd.add_argument("--spec", default="pipeline.json", help="pipeline spec (JSON)")
        cmd.add_argument("--state", default="state.json", help="pipeline state (JSON)")
        cmd.add_argument(
            "--dry-run",
            action="store_true",
            help="print the verdict without writing the state file",
        )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    spec_path = Path(args.spec).expanduser()
    state_path = Path(args.state).expanduser()
    try:
        spec = load_json(spec_path, "spec")
        validate_spec(spec)
        state = load_json(state_path, "state")
        base = spec_path.resolve().parent
        if args.command == "verify":
            report = verify(state, spec, base)
            emit(report)
            return EXIT_PROCEED if report["anchorOk"] else EXIT_ANCHOR_FAILED
        verdict, next_state = govern(state, spec, base)
        verdict["dryRun"] = bool(args.dry_run)
        emit(verdict)
        if not args.dry_run and next_state != state:
            write_state(state_path, next_state)
        return ACTION_EXIT[verdict["action"]]
    except SpecError as exc:
        print(f"anchor-gate: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
