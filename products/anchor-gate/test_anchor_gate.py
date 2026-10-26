#!/usr/bin/env python3
"""Autonomous tests for anchor-gate. Run: python3 -m unittest discover -p "test_*.py" -v"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import anchor_gate
from anchor_gate import SpecError, govern, main, verify


def spec_with(anchors, **extra) -> dict:
    spec = {
        "specVersion": "1.0",
        "maxAttempts": 2,
        "stages": {"draft": {"anchors": anchors, "next": None}},
    }
    spec.update(extra)
    return spec


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AnchorGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, text: str = "x") -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    # --- individual anchors -------------------------------------------------

    def test_nonempty_anchor(self):
        spec = spec_with([{"field": "brief", "kind": "nonempty"}])
        self.assertTrue(verify({"stage": "draft", "brief": "ok"}, spec, self.dir)["anchorOk"])
        self.assertFalse(verify({"stage": "draft", "brief": ""}, spec, self.dir)["anchorOk"])

    def test_file_anchor_and_min_bytes(self):
        self.write("out.md", "0123456789")
        spec = spec_with([{"field": "artifact", "kind": "file", "minBytes": 5}])
        ok = verify({"stage": "draft", "artifact": "out.md"}, spec, self.dir)
        self.assertTrue(ok["anchorOk"])

        spec = spec_with([{"field": "artifact", "kind": "file", "minBytes": 99}])
        small = verify({"stage": "draft", "artifact": "out.md"}, spec, self.dir)
        self.assertFalse(small["anchorOk"])
        self.assertIn("minBytes 99", small["checks"][0]["detail"])

        spec = spec_with([{"field": "artifact", "kind": "file"}])
        missing = verify({"stage": "draft", "artifact": "absent.md"}, spec, self.dir)
        self.assertFalse(missing["anchorOk"])
        self.assertIn("missing file", missing["checks"][0]["detail"])

    def test_sha256_full_match_and_mismatch(self):
        path = self.write("out.md", "content")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = spec_with([{"field": "digest", "kind": "sha256", "of": "artifact"}])

        good = verify({"stage": "draft", "artifact": "out.md", "digest": digest}, spec, self.dir)
        self.assertTrue(good["anchorOk"])

        bad = verify({"stage": "draft", "artifact": "out.md", "digest": "0" * 64}, spec, self.dir)
        self.assertFalse(bad["anchorOk"])

    def test_sha256_prefix_mode(self):
        path = self.write("out.md", "content")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = spec_with([{"field": "digest", "kind": "sha256", "of": "artifact", "prefix": True}])
        state = {"stage": "draft", "artifact": "out.md", "digest": digest[:12]}
        self.assertTrue(verify(state, spec, self.dir)["anchorOk"])

        state["digest"] = "deadbeefcafe"
        self.assertFalse(verify(state, spec, self.dir)["anchorOk"])

    def test_true_and_equals_anchors(self):
        spec = spec_with([
            {"field": "lintPassed", "kind": "true"},
            {"field": "verdict", "kind": "equals", "value": "OK"},
        ])
        state = {"stage": "draft", "lintPassed": True, "verdict": "OK"}
        self.assertTrue(verify(state, spec, self.dir)["anchorOk"])

        state["lintPassed"] = "yes"
        self.assertFalse(verify(state, spec, self.dir)["anchorOk"])

    def test_cmd_anchor_checks_exit_code(self):
        spec = spec_with([{"cmd": ["python3", "-c", "raise SystemExit(0)"], "kind": "cmd"}])
        self.assertTrue(verify({"stage": "draft"}, spec, self.dir)["anchorOk"])

        spec = spec_with([{"cmd": ["python3", "-c", "raise SystemExit(7)"], "kind": "cmd"}])
        report = verify({"stage": "draft"}, spec, self.dir)
        self.assertFalse(report["anchorOk"])
        self.assertIn("exit 7", report["checks"][0]["detail"])

        spec = spec_with([{"cmd": ["python3", "-c", "raise SystemExit(7)"], "kind": "cmd",
                           "expect": 7}])
        self.assertTrue(verify({"stage": "draft"}, spec, self.dir)["anchorOk"])

    def test_relative_paths_resolve_against_spec_directory(self):
        nested = self.dir / "pipeline"
        nested.mkdir()
        (nested / "out.md").write_text("here", encoding="utf-8")
        spec = spec_with([{"field": "artifact", "kind": "file"}])
        self.assertTrue(verify({"stage": "draft", "artifact": "out.md"}, spec, nested)["anchorOk"])
        self.assertFalse(verify({"stage": "draft", "artifact": "out.md"}, spec, self.dir)["anchorOk"])

    # --- governance ---------------------------------------------------------

    def failed_spec(self, max_attempts=2):
        return spec_with([{"field": "artifact", "kind": "file"}], maxAttempts=max_attempts)

    def test_proceed_resets_attempts(self):
        self.write("out.md", "done")
        spec = self.failed_spec()
        verdict, state = govern(
            {"stage": "draft", "artifact": "out.md", "stageAttempts": 1, "attemptsStage": "draft"},
            spec,
            self.dir,
        )
        self.assertEqual(verdict["action"], "proceed")
        self.assertEqual(state["stageAttempts"], 0)

    def test_anchor_failure_increments_attempts(self):
        spec = self.failed_spec(max_attempts=3)
        verdict, state = govern({"stage": "draft", "attemptsStage": "draft"}, spec, self.dir)
        self.assertEqual(verdict["action"], "anchor_failed")
        self.assertEqual(state["stageAttempts"], 1)

    def test_budget_exhaustion_parks(self):
        spec = self.failed_spec(max_attempts=2)
        state = {"stage": "draft", "stageAttempts": 1, "attemptsStage": "draft"}
        verdict, next_state = govern(state, spec, self.dir)
        self.assertEqual(verdict["action"], "park")
        self.assertEqual(next_state["stage"], "PARKED")

    def test_attempts_do_not_leak_across_stages(self):
        """A healthy stage must not inherit the previous stage's failures."""
        spec = {
            "maxAttempts": 2,
            "stages": {
                "draft": {"anchors": [{"field": "artifact", "kind": "file"}]},
                "review": {"anchors": [{"field": "note", "kind": "nonempty"}]},
            },
        }
        state = {"stage": "review", "note": "ok", "stageAttempts": 1, "attemptsStage": "draft"}
        verdict, next_state = govern(state, spec, self.dir)
        self.assertEqual(verdict["action"], "proceed")
        self.assertEqual(verdict["attempts"], 0)
        self.assertEqual(next_state["stageAttempts"], 0)

    def test_halt_stage_is_terminal(self):
        spec = spec_with([], haltStages=["PARKED", "SECURITY_HALT"])
        verdict, state = govern({"stage": "SECURITY_HALT", "stageAttempts": 0}, spec, self.dir)
        self.assertEqual(verdict["action"], "halt")
        self.assertEqual(state["stage"], "SECURITY_HALT")

    def test_bounce_signal_returns_to_earlier_stage(self):
        spec = {
            "maxAttempts": 2,
            "stages": {"scout": {"anchors": []}, "draft": {"anchors": []}},
            "bounceSignal": {"field": "verdict", "value": "CONTEXT_INSUFFICIENT", "to": "scout"},
        }
        state = {"stage": "draft", "verdict": "CONTEXT_INSUFFICIENT", "stageAttempts": 1,
                 "attemptsStage": "draft", "backwardBounces": 2}
        verdict, next_state = govern(state, spec, self.dir)
        self.assertEqual(verdict["action"], "bounce")
        self.assertEqual(next_state["stage"], "scout")
        self.assertEqual(next_state["stageAttempts"], 0)
        self.assertEqual(next_state["backwardBounces"], 3)

    # --- CLI ----------------------------------------------------------------

    def write_pipeline(self, stage="draft", state_extra=None) -> tuple[Path, Path]:
        spec_path = self.dir / "pipeline.json"
        spec_path.write_text(json.dumps(self.failed_spec()), encoding="utf-8")
        state = {"stage": stage}
        state.update(state_extra or {})
        state_path = self.dir / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return spec_path, state_path

    def test_verify_exit_codes(self):
        spec_path, state_path = self.write_pipeline()
        args = ["verify", "--spec", str(spec_path), "--state", str(state_path)]
        self.assertEqual(main(args), anchor_gate.EXIT_ANCHOR_FAILED)

        self.write("out.md", "done")
        state_path.write_text(json.dumps({"stage": "draft", "artifact": "out.md"}), encoding="utf-8")
        self.assertEqual(main(args), anchor_gate.EXIT_PROCEED)

    def test_dry_run_leaves_state_untouched(self):
        spec_path, state_path = self.write_pipeline()
        before = state_path.read_text(encoding="utf-8")
        code = main(["govern", "--spec", str(spec_path), "--state", str(state_path), "--dry-run"])
        self.assertEqual(code, anchor_gate.EXIT_ANCHOR_FAILED)
        self.assertEqual(state_path.read_text(encoding="utf-8"), before)

    def test_govern_persists_incremented_attempts(self):
        spec_path, state_path = self.write_pipeline()
        code = main(["govern", "--spec", str(spec_path), "--state", str(state_path)])
        self.assertEqual(code, anchor_gate.EXIT_ANCHOR_FAILED)
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stageAttempts"], 1)
        self.assertEqual(saved["attemptsStage"], "draft")

    def test_park_exit_code(self):
        spec_path, state_path = self.write_pipeline(state_extra={"stageAttempts": 1,
                                                                "attemptsStage": "draft"})
        self.assertEqual(main(["govern", "--spec", str(spec_path), "--state", str(state_path)]),
                         anchor_gate.EXIT_PARK)

    def test_halt_exit_code(self):
        spec_path = self.dir / "pipeline.json"
        spec = spec_with([], haltStages=["SECURITY_HALT"])
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        state_path = self.dir / "state.json"
        state_path.write_text(json.dumps({"stage": "SECURITY_HALT"}), encoding="utf-8")
        self.assertEqual(main(["govern", "--spec", str(spec_path), "--state", str(state_path)]),
                         anchor_gate.EXIT_HALT)

    def test_unknown_kind_is_a_config_error(self):
        spec = spec_with([{"field": "x", "kind": "vibes"}])
        with self.assertRaises(SpecError):
            anchor_gate.validate_spec(spec)

    def test_shell_string_command_is_rejected(self):
        spec = spec_with([{"cmd": "rm -rf /", "kind": "cmd"}])
        with self.assertRaises(SpecError):
            anchor_gate.validate_spec(spec)

    def test_state_stage_must_be_declared(self):
        with self.assertRaises(SpecError):
            verify({"stage": "ghost"}, self.failed_spec(), self.dir)

    def test_missing_spec_exits_config(self):
        state_path = self.dir / "state.json"
        state_path.write_text(json.dumps({"stage": "draft"}), encoding="utf-8")
        code = main(["verify", "--spec", str(self.dir / "nope.json"), "--state", str(state_path)])
        self.assertEqual(code, anchor_gate.EXIT_CONFIG)

    def test_invalid_json_state_exits_config(self):
        spec_path, state_path = self.write_pipeline()
        state_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(main(["verify", "--spec", str(spec_path), "--state", str(state_path)]),
                         anchor_gate.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
