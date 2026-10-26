#!/usr/bin/env python3
"""Autonomous tests for recall-ladder. Run: python3 -m unittest discover -s . -p "test_*.py" -v"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import recall_ladder as rl

HERE = Path(__file__).resolve().parent
OK, USAGE, ATE_ALL, UNREACHABLE = 0, 2, 3, 4


def bank(*scores, ok=True, error=None):
    payload = {"ok": ok, "results": [{"id": f"r{index}", "rerankerScore": score, "content": f"chunk {index}"}
                                     for index, score in enumerate(scores)]}
    if error:
        payload["error"] = error
    return payload


class ParsingTests(unittest.TestCase):
    def test_bank_response_is_parsed(self):
        entries = rl.parse_response(bank(0.9, 0.2))
        self.assertEqual([entry["score"] for entry in entries], [0.9, 0.2])
        self.assertEqual(entries[0]["id"], "r0")
        self.assertEqual(entries[1]["text"], "chunk 1")

    def test_bare_list_and_numbers_are_accepted(self):
        self.assertEqual([e["score"] for e in rl.parse_response([0.5, 1])], [0.5, 1.0])
        self.assertEqual([e["score"] for e in rl.parse_response([{"score": 0.4}])], [0.4])

    def test_empty_results_are_empty_not_an_error(self):
        self.assertEqual(rl.parse_response({"ok": True, "results": []}), [])
        self.assertEqual(rl.parse_response({"ok": True, "results": None}), [])

    def test_missing_results_is_a_shape_error(self):
        with self.assertRaises(rl.ResponseError):
            rl.parse_response({"ok": True})

    def test_non_object_result_is_rejected(self):
        with self.assertRaises(rl.ResponseError):
            rl.parse_response({"results": ["plain string"]})

    def test_missing_or_broken_score_is_rejected(self):
        with self.assertRaises(rl.ResponseError):
            rl.parse_response({"results": [{"content": "no score"}]})
        with self.assertRaises(rl.ResponseError):
            rl.parse_response({"results": [{"rerankerScore": "high"}]})

    def test_string_score_is_coerced(self):
        self.assertEqual(rl.parse_response({"results": [{"rerankerScore": "0.7"}]})[0]["score"], 0.7)

    def test_long_text_is_trimmed(self):
        entry = rl.parse_response({"results": [{"rerankerScore": 0.5, "content": "x" * 900}]})[0]
        self.assertEqual(len(entry["text"]), 240)


class SourceHealthTests(unittest.TestCase):
    def test_ok_false_means_unreachable(self):
        self.assertFalse(rl.source_ok_of({"ok": False, "results": []}))
        self.assertEqual(rl.verdict([], 0.25, source_ok=False)["status"], "source_unreachable")

    def test_error_field_means_unreachable(self):
        self.assertFalse(rl.source_ok_of(bank(0.9, error="timeout")))
        self.assertTrue(rl.source_ok_of(bank(0.9)))

    def test_bare_list_is_assumed_healthy(self):
        self.assertTrue(rl.source_ok_of([1, 2]))


class VerdictTests(unittest.TestCase):
    def test_kept_results_are_ok(self):
        result = rl.verdict(rl.parse_response(bank(0.9, 0.2)), 0.25)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["ok"])
        self.assertEqual((result["kept"], result["total"]), (1, 2))
        self.assertEqual(result["keptIds"], ["r0"])

    def test_threshold_equal_to_score_counts_as_kept(self):
        self.assertEqual(rl.verdict(rl.parse_response(bank(0.25)), 0.25)["kept"], 1)

    def test_all_dropped_is_threshold_ate_all_not_empty_bank(self):
        result = rl.verdict(rl.parse_response(bank(0.22, 0.18, 0.1)), 0.25)
        self.assertEqual(result["status"], "threshold_ate_all")
        self.assertFalse(result["ok"])
        self.assertEqual(result["bestScore"], 0.22)

    def test_no_rows_at_all_is_an_empty_bank(self):
        self.assertEqual(rl.verdict([], 0.25)["status"], "bank_empty")

    def test_empty_bank_differs_from_dead_source(self):
        self.assertNotEqual(
            rl.verdict([], 0.25)["status"], rl.verdict([], 0.25, source_ok=False)["status"]
        )


class LadderTests(unittest.TestCase):
    def test_every_rung_is_reported(self):
        rungs = rl.ladder(rl.parse_response(bank(0.99, 0.4, 0.2)))
        self.assertEqual([rung["threshold"] for rung in rungs], list(rl.LADDER))
        self.assertEqual([rung["kept"] for rung in rungs], [0, 1, 2, 2, 3, 3])

    def test_recommendation_picks_the_highest_usable_rung(self):
        entries = rl.parse_response(bank(0.22, 0.18))
        self.assertEqual(rl.recommend_threshold(entries), 0.15)
        self.assertEqual(rl.recommend_threshold(rl.parse_response(bank(0.99))), 0.5)

    def test_recommendation_refuses_to_go_below_the_floor(self):
        entries = rl.parse_response(bank(0.1, 0.05))
        self.assertIsNone(rl.recommend_threshold(entries))
        self.assertEqual(rl.recommend_threshold(entries, floor=0.0), 0.0)

    def test_recommendation_on_empty_entries_is_none(self):
        self.assertIsNone(rl.recommend_threshold([]))


class ExplainTests(unittest.TestCase):
    def test_threshold_case_suggests_a_number(self):
        report = rl.explain(bank(0.22), 0.25)
        self.assertEqual(report["status"], "threshold_ate_all")
        self.assertEqual(report["recommendedThreshold"], 0.15)
        self.assertIn("0.15", report["action"])

    def test_hopeless_case_says_change_the_query(self):
        report = rl.explain(bank(0.05), 0.25)
        self.assertIsNone(report["recommendedThreshold"])
        self.assertIn("менять запрос", report["action"])

    def test_unreachable_case_reports_no_recommendation(self):
        report = rl.explain({"ok": False, "results": []})
        self.assertEqual(report["status"], "source_unreachable")
        self.assertIsNone(report["recommendedThreshold"])
        self.assertIn("ошибкой", report["action"])

    def test_healthy_case_keeps_the_threshold(self):
        report = rl.explain(bank(0.9), 0.25)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["action"], "оставить порог 0.25")

    def test_report_carries_the_whole_curve(self):
        report = rl.explain(bank(0.5))
        self.assertEqual(len(report["rungs"]), len(rl.LADDER))
        self.assertTrue(report["sourceOk"])


class LessonContractTests(unittest.TestCase):
    GOOD = (
        "claim: Порог 0.25 съел все шесть записей банка\n"
        "anchor: sha256:9f2c1ab34d5e6f708192a3b4c5d6e7f8\n"
        "evidence: ответ банка с kept 0 из 6 и min_reranker 0.25\n"
    )

    def test_complete_lesson_passes(self):
        report = rl.check_lesson(self.GOOD)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["anchors"][0][:7], "sha256:")

    def test_missing_fields_are_named(self):
        report = rl.check_lesson("claim: что-то произошло и это важно\n")
        self.assertFalse(report["ok"])
        codes = [row["code"] for row in report["problems"]]
        self.assertIn("missing_fields", codes)
        self.assertEqual(report["problems"][0]["fields"], ["anchor", "evidence"])

    def test_anchor_must_be_machine_checkable(self):
        text = self.GOOD.replace("sha256:9f2c1ab34d5e6f708192a3b4c5d6e7f8", "я посмотрел глазами")
        report = rl.check_lesson(text)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"][0]["code"], "anchor_not_machine_checkable")

    def test_path_anchor_is_accepted(self):
        text = self.GOOD.replace("sha256:9f2c1ab34d5e6f708192a3b4c5d6e7f8", "Drafts/goal-lint-latest.json")
        self.assertTrue(rl.check_lesson(text)["ok"])

    def test_short_claim_is_rejected(self):
        text = self.GOOD.replace("Порог 0.25 съел все шесть записей банка", "сломалось")
        report = rl.check_lesson(text)
        self.assertIn("too_short", [row["code"] for row in report["problems"]])

    def test_extra_fields_do_not_break_the_contract(self):
        text = self.GOOD + "bank: metites-episodes\n"
        report = rl.check_lesson(text)
        self.assertTrue(report["ok"], report)
        self.assertIn("bank", report["fields"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(HERE / "recall_ladder.py"), *args],
            capture_output=True, text=True, input=stdin, cwd=HERE,
        )

    def write(self, payload) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        handle.write(json.dumps(payload))
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_exit_codes_follow_the_verdict(self):
        self.assertEqual(self.run_cli("explain", "--response", self.write(bank(0.9))).returncode, OK)
        self.assertEqual(self.run_cli("explain", "--response", self.write(bank(0.2))).returncode, ATE_ALL)
        self.assertEqual(self.run_cli("explain", "--response", self.write({"ok": False, "results": []})).returncode, UNREACHABLE)

    def test_json_output_is_machine_readable(self):
        result = self.run_cli("explain", "--response", self.write(bank(0.22)), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "threshold_ate_all")
        self.assertEqual(payload["recommendedThreshold"], 0.15)

    def test_broken_json_is_a_usage_error(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        handle.write("{not json")
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        self.assertEqual(self.run_cli("explain", "--response", handle.name).returncode, USAGE)

    def test_stdin_response(self):
        result = self.run_cli("explain", "--response", "-", stdin=json.dumps(bank(0.9)))
        self.assertEqual(result.returncode, OK)

    def test_lesson_command_reports_both_outcomes(self):
        good = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        good.write(LessonContractTests.GOOD)
        good.close()
        self.addCleanup(lambda: Path(good.name).unlink(missing_ok=True))
        self.assertEqual(self.run_cli("lesson", "--file", good.name).returncode, OK)

        bad = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        bad.write("claim: коротко\n")
        bad.close()
        self.addCleanup(lambda: Path(bad.name).unlink(missing_ok=True))
        result = self.run_cli("lesson", "--file", bad.name, "--json")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
