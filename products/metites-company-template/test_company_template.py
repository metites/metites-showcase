#!/usr/bin/env python3
"""Tests for the exported Paperclip-style company package.

Run: python3 -m unittest discover -s . -p "test_*.py" -v

The package claims three things, and each one is checked as an artefact, not as a
promise: the frontmatter of every file parses, every cross-file link resolves, and
nothing private (home paths, API keys, tokens) leaves the repository.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

import export_company as ec

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import audit_public  # noqa: E402  (путь к сканеру зависит от репозитория)

# Признаки приватного собираются конкатенацией: иначе сам тест станет утечкой.
HOME_MARK = "/" + "home" + "/"
OWNER_MARK = "vrum" + "gel"
SECRET_MARKERS = (
    "sk" + "-or-v1-",
    "TELEGRAM_BOT_TOKEN" + "=",
    "SCRAPECREATORS_API_KEY" + "=",
    "DPI_TOKEN" + "=",
)
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|xoxb-[0-9]{6,}|ghp_[A-Za-z0-9]{20,})")

REQUIRED_AGENT_KEYS = ("schema", "name", "slug", "role", "reportsTo", "skills")
REQUIRED_TASK_KEYS = ("schema", "id", "title", "owner", "cadence", "acceptance")
ROLE_SLUGS = ("planner", "critic", "scout", "archivist", "editor", "worker", "guard", "news")
TASK_SLUGS = ("morning-goal-lint", "news-hfs-sweep", "daily-signal-dispatch", "aeo-discovery")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML reader for the shapes the generator emits (scalars + lists)."""
    if not text.startswith("---\n"):
        raise AssertionError("файл не начинается с YAML-шапки")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise AssertionError("YAML-шапка не закрыта")
    block, body = text[4:end], text[end + 5 :]
    data: dict = {}
    key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - "):
            if key is None or not isinstance(data.get(key), list):
                raise AssertionError(f"элемент списка без ключа: {line!r}")
            data[key].append(line[4:].strip().strip('"'))
            continue
        if ":" not in line:
            raise AssertionError(f"строка шапки не разобрана: {line!r}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value == "":
            data[key] = []
        elif value.lstrip("-").isdigit() and not value.startswith("-"):
            data[key] = int(value)
        else:
            data[key] = value.strip('"')
    return data, body


class ExportedTreeTests(unittest.TestCase):
    """Одно поколение пакета на весь класс: тесты смотрят на реальный экспорт."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "company"
        cls.report = ec.export(cls.out, force=True)
        cls.files = sorted(p for p in cls.out.rglob("*.md"))
        cls.texts = {p.relative_to(cls.out).as_posix(): p.read_text(encoding="utf-8") for p in cls.files}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_all_fifteen_files_are_exported(self) -> None:
        self.assertEqual(self.report["count"], 15)
        self.assertEqual(len(self.texts), 15)

    def test_every_file_has_parseable_frontmatter(self) -> None:
        for rel, text in self.texts.items():
            with self.subTest(file=rel):
                head, body = parse_frontmatter(text)
                self.assertTrue(head.get("schema", "").startswith("paperclip/"))
                self.assertTrue(body.strip(), "тело файла пустое")

    def test_eight_roles_with_required_fields(self) -> None:
        agents = {rel.split("/")[1]: parse_frontmatter(text)[0] for rel, text in self.texts.items() if rel.startswith("agents/")}
        self.assertEqual(tuple(sorted(agents)), tuple(sorted(ROLE_SLUGS)))
        for slug, head in agents.items():
            with self.subTest(agent=slug):
                for key in REQUIRED_AGENT_KEYS:
                    self.assertTrue(head.get(key), f"{slug}: поле {key} пустое")
                self.assertEqual(head["slug"], slug)
                self.assertTrue(head["skills"], "у агента нет скиллов")

    def test_reports_to_links_resolve(self) -> None:
        agents = {rel.split("/")[1]: parse_frontmatter(text)[0] for rel, text in self.texts.items() if rel.startswith("agents/")}
        allowed = set(agents) | {"owner"}
        for slug, head in agents.items():
            with self.subTest(agent=slug):
                self.assertIn(head["reportsTo"], allowed)
        self.assertEqual(agents["planner"]["reportsTo"], "owner", "у планировщика нет начальника-человека")

    def test_company_includes_resolve_to_files(self) -> None:
        head, _ = parse_frontmatter(self.texts["COMPANY.md"])
        for rel in list(head["agents"]) + list(head["tasks"]) + list(head["projects"]):
            with self.subTest(link=rel):
                self.assertIn(rel, self.texts)
        for team in head["teams"]:
            self.assertIn(f"teams/{team}/TEAM.md", self.texts)

    def test_team_lists_every_agent(self) -> None:
        head, _ = parse_frontmatter(self.texts["teams/metites-lab/TEAM.md"])
        self.assertEqual(tuple(sorted(head["agents"])), tuple(sorted(ROLE_SLUGS)))
        self.assertIn(head["coordinator"], head["agents"])

    def test_project_tasks_resolve(self) -> None:
        head, _ = parse_frontmatter(self.texts["projects/PROJECT.md"])
        self.assertEqual(tuple(sorted(head["tasks"])), tuple(sorted(TASK_SLUGS)))
        for slug in head["tasks"]:
            self.assertIn(f"tasks/{slug}/TASK.md", self.texts)

    def test_every_task_is_complete_and_owned(self) -> None:
        tasks = {rel.split("/")[1]: parse_frontmatter(text)[0] for rel, text in self.texts.items() if rel.startswith("tasks/")}
        self.assertEqual(tuple(sorted(tasks)), tuple(sorted(TASK_SLUGS)))
        for slug, head in tasks.items():
            with self.subTest(task=slug):
                for key in REQUIRED_TASK_KEYS:
                    self.assertTrue(head.get(key), f"{slug}: поле {key} пустое")
                self.assertEqual(head["id"], slug)
                self.assertIn(head["owner"], ROLE_SLUGS, "владелец задачи должен быть слагом роли")
                self.assertTrue(head["inputs"] and head["outputs"])
                self.assertTrue(head["acceptance"])

    def test_goal_tree_names_horizons_and_criteria(self) -> None:
        text = self.texts["COMPANY.md"]
        for horizon in ("H1", "H2", "H3"):
            self.assertIn(horizon, text)
        for criterion in ("AC-GOAL-001", "AC-GOAL-002", "AC-GOAL-003", "AC-MON-001"):
            self.assertIn(criterion, text)

    def test_no_private_paths_or_secrets(self) -> None:
        for rel, text in self.texts.items():
            with self.subTest(file=rel):
                self.assertNotIn(HOME_MARK, text, "приватный домашний путь в пакете")
                self.assertNotIn(OWNER_MARK, text)
                for marker in SECRET_MARKERS:
                    self.assertNotIn(marker, text)
                self.assertIsNone(SECRET_RE.search(text), "похоже на секрет")

    def test_public_audit_finds_nothing(self) -> None:
        for rel, text in self.texts.items():
            with self.subTest(file=rel):
                self.assertEqual(audit_public.scan_text(text, rel), [])

    def test_export_is_idempotent_and_check_agrees(self) -> None:
        second = ec.export(self.out, force=False)
        self.assertTrue(second["ok"], "повторный экспорт изменил бы файлы")
        self.assertEqual(second["skipped"], [])
        report = ec.check(self.out)
        self.assertTrue(report["ok"])
        self.assertEqual(report["extra"], [])

    def test_check_detects_drift_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "company"
            ec.export(target, force=True)
            (target / "agents/planner/AGENTS.md").write_text("---\nschema: paperclip/agent@1\n---\nвручную\n", encoding="utf-8")
            (target / "tasks/aeo-discovery/TASK.md").unlink()
            report = ec.check(target)
            self.assertFalse(report["ok"])
            self.assertIn("agents/planner/AGENTS.md", report["stale"])
            self.assertIn("tasks/aeo-discovery/TASK.md", report["missing"])

    def test_export_refuses_to_clobber_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "company"
            ec.export(target, force=True)
            edited = target / "COMPANY.md"
            edited.write_text("правка владельца\n", encoding="utf-8")
            report = ec.export(target, force=False)
            self.assertFalse(report["ok"])
            self.assertEqual(report["skipped"], ["COMPANY.md"])
            self.assertEqual(edited.read_text(encoding="utf-8"), "правка владельца\n")
            self.assertTrue(ec.export(target, force=True)["ok"])

    def test_cli_check_exit_codes(self) -> None:
        self.assertEqual(ec.main(["--out", str(self.out), "--check"]), 0)
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "company"
            self.assertEqual(ec.main(["--out", str(empty), "--check"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
