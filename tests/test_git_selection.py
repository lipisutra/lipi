"""Границы отбора Git в корне репозитория и во вложенном проекте."""

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.checker.workflow import decision_names, next_number


class GitSelectionTests(unittest.TestCase):
    def project(self, nested, ignore):
        temporary = tempfile.TemporaryDirectory(prefix="lipi-selection-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        repo = base / "repository"
        root = repo / "component" if nested else repo
        prefix = "component/" if nested else ""
        support.w(repo / ".gitignore", "".join("/" + prefix + path + "\n" for path in ignore))
        support.w(root / "lipi.json", "{}\n")
        support.w(root / "docs/README.md", '# Описание <a id="intro"></a>\n')
        support.git_init(repo)
        return base, repo, root

    # @trace docs/ru/codes.md#a3
    def test_audit_filters_ignored_entries_and_keeps_tracked_and_untracked(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                _, repo, root = self.project(nested, ["src/ignored.py", "src/tracked.py"])
                support.set_config(root, entry=["^def entry"])
                for name in ("ignored", "tracked", "untracked"):
                    support.w(root / ("src/" + name + ".py"), "def entry():\n    pass\n")
                code, output = support.git(repo, "add", "-f", str(root / "src/tracked.py"))
                self.assertEqual(code, 0, output)
                _, result = support.check_json(root, "--audit")
                self.assertIsNotNone(result)
                self.assertEqual({item["file"] for item in result["warnings"] if item["code"] == "A3"},
                                 {"src/tracked.py", "src/untracked.py"})

    # @trace ADR-016
    def test_ignored_symlink_is_never_resolved_or_read(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                base, _, root = self.project(nested, ["src/ignored.py"])
                outside = base / "outside.py"
                support.w(outside, "# %s docs/absent.md#missing\n" % support.TAG)
                ignored = root / "src/ignored.py"
                ignored.parent.mkdir()
                ignored.symlink_to(outside)
                visible = root / "src/visible.py"
                visible.symlink_to(ignored.name)
                escaped = root / "src/escaped.py"
                escaped.symlink_to(outside)
                original = Path.readlink

                def readlink(path):
                    self.assertNotEqual(path, ignored)
                    return original(path)

                with patch.object(Path, "readlink", readlink):
                    project = Project(root, load_config(root, None))
                    self.assertIsNone(project.file_path(ignored))
                    self.assertIsNone(project.file_path(visible))
                    self.assertIsNone(project.file_path(escaped))
                    self.assertFalse({ignored, visible, escaped}.intersection(project.walk_files()))

                code, output = support.check(root)
                self.assertEqual(code, 0, output)
                self.assertNotIn("absent.md", output)

    # @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6
    def test_ignored_page_cannot_be_a_trace_or_covers_target(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                _, _, root = self.project(nested, ["docs/hidden.md"])
                target = "docs/hidden.md#hidden"
                support.w(root / "docs/hidden.md", '# Скрыто <a id="hidden"></a>\n')
                support.w(root / "docs/README.md", "# Описание\n\n<!-- covers: %s -->\n" % target)
                support.w(root / "src/consumer.py", "# %s %s\n" % (support.TAG, target))

                code, result = support.check_json(root)
                self.assertEqual(code, 1, result)
                self.assertEqual({item["code"] for item in result["errors"]}, {"T1", "D6"})
                self.assertTrue(all(target.partition("#")[0] in item["message"]
                                    for item in result["errors"]))

    # @trace docs/ru/commands.md#new
    def test_ignored_work_name_reserves_number_without_reading_contents(self):
        _, _, root = self.project(True, ["workflow/issue/2026/iss-009-hidden.md"])
        hidden = root / "workflow/issue/2026/iss-009-hidden.md"
        support.wb(hidden, b"\xff")
        with patch.object(Path, "read_text", side_effect=AssertionError("read work contents")):
            self.assertEqual(next_number(Project(root, {"workflow": "workflow"}), "iss"), "010")
        code, output = support.cli(root, "new", "iss", "Next", "bug", "--format", "json")
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["id"], "ISS-010")
        self.assertEqual(hidden.read_bytes(), b"\xff")

    # @trace docs/ru/commands.md#new-decision
    def test_symbolic_link_does_not_reserve_work_numbers_outside_the_project(self):
        base, _, root = self.project(False, [".agents", "workflow/adr"])
        outside = base / "outside"
        support.w(outside / "lipi-feedback/iss-099-private.md", "# Private\n")
        alias = root / ".agents"
        alias.symlink_to(outside, target_is_directory=True)
        support.w(outside / "decisions/0099-private.md", "# Private ADR\n")
        decisions = root / "workflow/adr"
        decisions.parent.mkdir()
        decisions.symlink_to(outside / "decisions", target_is_directory=True)
        with patch.object(Path, "readlink", side_effect=AssertionError("resolve work link")), \
                patch.object(Path, "read_text", side_effect=AssertionError("read work contents")):
            project = Project(root, {"workflow": "workflow"})
            self.assertEqual(next_number(project, "iss"), "001")
            self.assertEqual(next_number(project, "adr"), "001")
            self.assertEqual(decision_names(project), [])
            self.assertEqual(decision_names(project, include_archived=True), [])

    # @trace docs/ru/codes.md#d1
    def test_configured_external_git_directory_has_its_own_inventory(self):
        _, repo, root = self.project(True, [])
        support.set_config(root, docs="../manual")
        manual = repo / "manual"
        support.w(repo / ".gitignore", "/manual/hidden.md\n")
        support.w(manual / "hidden.md", "# Скрыто\n\n[Ошибка](missing.md)\n")
        support.w(manual / "README.md", "# Описание\n\n[Открыто](shown.md)\n")
        support.w(manual / "shown.md", "# Открыто\n\n[Ошибка](missing.md)\n")
        code, output = support.git(repo, "add", "manual/shown.md")
        self.assertEqual(code, 0, output)
        _, result = support.check_json(root)
        self.assertEqual([(item["code"], item["file"]) for item in result["errors"]],
                         [("D1", "../manual/shown.md")])

    # @trace docs/ru/codes.md#w7
    def test_index_omits_ignored_outputs_and_preserves_their_contents(self):
        _, _, root = self.project(True, ["workflow/index/issues.md", "workflow/index/audits.md"])
        ignored = root / "workflow/index/issues.md"
        support.wb(ignored, b"\xff")

        code, output = support.cli(root, "index")

        self.assertEqual(code, 0, output)
        self.assertEqual(ignored.read_bytes(), b"\xff")
        self.assertFalse((root / "workflow/index/audits.md").exists())
        index = (root / "workflow/INDEX.md").read_text(encoding="utf-8")
        self.assertIn("(index/plans.md)", index)
        self.assertNotIn("(index/issues.md)", index)
        self.assertNotIn("(index/audits.md)", index)
