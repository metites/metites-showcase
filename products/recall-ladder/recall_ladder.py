#!/usr/bin/env python3
"""recall-ladder — read a zero-result memory recall honestly, and pick a threshold.

An episodic memory bank answers `{"ok": true, "results": []}` for two completely
different situations: nothing relevant exists, or the relevance threshold threw
everything away. `kept: 0` is not evidence of an empty bank; it is evidence of an
empty *result set*. The difference decides whether the pipeline should widen the
query, lower the threshold, or record a new lesson.

This tool reads the raw response, shows what each threshold on a ladder would keep,
and names the verdict. It also validates the lesson contract we write back to the
bank: a lesson without an artifact anchor is an opinion.

    python3 recall_ladder.py explain --response bank.json --threshold 0.25
    python3 recall_ladder.py lesson --file lesson.md

Python 3.9+. Standard library only. No network access, no model in the path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LADDER = (1.0, 0.5, 0.35, 0.25, 0.15, 0.0)
DEFAULT_THRESHOLD = 0.25
# Ниже этого порога «похожесть» уже не отличает релевантное от соседнего по смыслу,
# поэтому рекомендация не спускается ниже без явного разрешения.
DEFAULT_FLOOR = 0.15
ANCHOR_RE = re.compile(r"(sha256:[0-9a-f]{16,64}|\b[0-9a-f]{16,64}\b|\b(?:Wiki|Raw|Drafts|scripts|tests)/[\w./-]+)")
LESSON_FIELDS = ("claim", "anchor", "evidence")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_THRESHOLD_ATE_ALL = 3
EXIT_SOURCE_UNREACHABLE = 4


class ResponseError(ValueError):
    """The response is not a shape this tool can reason about."""


def entry_of(item) -> dict:
    """Normalises one result: score, text, id — whatever the bank chose to send."""
    if isinstance(item, (int, float)):
        return {"score": float(item), "text": "", "id": None}
    if not isinstance(item, dict):
        raise ResponseError(f"result is not an object: {type(item).__name__}")
    score = item.get("rerankerScore", item.get("score", item.get("relevance")))
    if score is None:
        raise ResponseError("result has no score (rerankerScore/score/relevance)")
    try:
        value = float(score)
    except (TypeError, ValueError) as exc:
        raise ResponseError(f"score is not a number: {score!r}") from exc
    text = item.get("content", item.get("text", item.get("chunk", "")))
    return {
        "score": value,
        "text": " ".join(str(text or "").split())[:240],
        "id": item.get("id") or item.get("uuid"),
    }


def parse_response(payload) -> list:
    """Accepts a bank response object, a bare list, or the `results` field of either."""
    results = payload
    if isinstance(payload, dict):
        if "results" not in payload:
            raise ResponseError("response has no `results` field")
        results = payload["results"]
    if results is None:
        return []
    if not isinstance(results, list):
        raise ResponseError(f"`results` is {type(results).__name__}, not a list")
    return [entry_of(item) for item in results]


def source_ok_of(payload) -> bool:
    """`ok: false` or an error string means the bank did not answer, not that it is empty."""
    if not isinstance(payload, dict):
        return True
    if payload.get("ok") is False:
        return False
    return not payload.get("error")


def verdict(entries: list, threshold: float = DEFAULT_THRESHOLD, *, source_ok: bool = True) -> dict:
    """Four different facts behind the same `kept: 0`."""
    kept = [entry for entry in entries if entry["score"] >= threshold]
    if not source_ok:
        status = "source_unreachable"
    elif not entries:
        # Банк ответил честно: записей нет вообще.
        status = "bank_empty"
    elif not kept:
        status = "threshold_ate_all"
    else:
        status = "ok"
    return {
        "status": status,
        "ok": status == "ok",
        "kept": len(kept),
        "total": len(entries),
        "threshold": threshold,
        "bestScore": max((entry["score"] for entry in entries), default=None),
        "keptIds": [entry["id"] for entry in kept][:5],
    }


def ladder(entries: list, *, thresholds=LADDER) -> list:
    """What every rung would keep: the whole curve, not just the chosen threshold."""
    rungs = []
    for threshold in thresholds:
        kept = [entry for entry in entries if entry["score"] >= threshold]
        rungs.append({"threshold": threshold, "kept": len(kept), "ids": [entry["id"] for entry in kept][:5]})
    return rungs


def recommend_threshold(entries: list, *, floor: float = DEFAULT_FLOOR, thresholds=LADDER):
    """Highest rung that keeps something, but never below the floor.

    Returns None when even the floor keeps nothing: then the honest next step is a
    new query or a new lesson, not a lower number.
    """
    usable = [value for value in thresholds if value >= floor]
    for value in usable:
        if any(entry["score"] >= value for entry in entries):
            return value
    return None


def explain(payload, threshold: float = DEFAULT_THRESHOLD, *, floor: float = DEFAULT_FLOOR) -> dict:
    entries = parse_response(payload)
    source_ok = source_ok_of(payload)
    head = verdict(entries, threshold, source_ok=source_ok)
    recommended = recommend_threshold(entries, floor=floor) if entries and source_ok else None
    rungs = ladder(entries)
    if not source_ok:
        action = "проверить банк: ответ с ошибкой, а не пустая выдача"
    elif head["status"] == "bank_empty":
        action = "записать урок: банк ответил и записей нет"
    elif head["status"] == "threshold_ate_all":
        action = (
            f"снизить порог до {recommended}" if recommended is not None
            else f"порог не спасёт: лучший балл {head['bestScore']} — менять запрос, а не число"
        )
    else:
        action = f"оставить порог {threshold}"
    return {**head, "sourceOk": source_ok, "rungs": rungs, "recommendedThreshold": recommended, "action": action}


def read_lesson(text: str) -> dict:
    """Parses `field: value` lines of a lesson block; extra fields are kept as-is."""
    fields = {}
    for line in str(text or "").splitlines():
        match = re.match(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$", line)
        if match:
            fields[match.group(1).lower()] = match.group(2)
    return fields


def check_lesson(text: str) -> dict:
    """A lesson is accepted only with a claim, an evidence anchor and its trace."""
    fields = read_lesson(text)
    missing = [name for name in LESSON_FIELDS if not fields.get(name)]
    anchors = ANCHOR_RE.findall(fields.get("anchor", ""))
    problems = []
    if missing:
        problems.append({"code": "missing_fields", "fields": missing})
    if fields.get("anchor") and not anchors:
        problems.append({"code": "anchor_not_machine_checkable", "anchor": fields["anchor"][:120]})
    too_short = [name for name in ("claim", "evidence") if fields.get(name) and len(fields[name]) < 20]
    if too_short:
        problems.append({"code": "too_short", "fields": too_short})
    return {"ok": not problems, "problems": problems, "fields": sorted(fields), "anchors": anchors[:3]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recall-ladder", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    explain_cmd = sub.add_parser("explain", help="Read a bank response and name the verdict")
    explain_cmd.add_argument("--response", required=True, help="Path to the raw bank JSON (or - for stdin)")
    explain_cmd.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    explain_cmd.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    explain_cmd.add_argument("--json", action="store_true")
    lesson_cmd = sub.add_parser("lesson", help="Validate a lesson against the contract")
    lesson_cmd.add_argument("--file", required=True)
    lesson_cmd.add_argument("--json", action="store_true")
    return parser


def load_json_arg(path: str):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "explain":
        try:
            payload = load_json_arg(args.response)
        except (OSError, ValueError) as exc:
            print(f"cannot read response: {exc}", file=sys.stderr)
            return EXIT_USAGE
        try:
            report = explain(payload, args.threshold, floor=args.floor)
        except ResponseError as exc:
            print(f"unexpected response shape: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"{report['status']}: kept {report['kept']}/{report['total']} at {report['threshold']}")
            print(f"best score: {report['bestScore']} | recommended: {report['recommendedThreshold']}")
            print(f"next: {report['action']}")
            for rung in report["rungs"]:
                print(f"  >= {rung['threshold']:<5} keeps {rung['kept']}")
        if report["status"] == "source_unreachable":
            return EXIT_SOURCE_UNREACHABLE
        if report["status"] == "threshold_ate_all":
            return EXIT_THRESHOLD_ATE_ALL
        return EXIT_OK

    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read lesson: {exc}", file=sys.stderr)
        return EXIT_USAGE
    report = check_lesson(text)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("lesson ok" if report["ok"] else f"lesson rejected: {report['problems']}")
    return EXIT_OK if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
