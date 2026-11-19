"""Комплект указателей: шапки, адреса, владение и откат."""

import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import support
from lipi.checker.conventions import K_CLOSED, K_CREATED, K_RESULT, K_STATUS, K_UPDATED, STATUSES
from lipi.checker.model import Page, Project
from lipi.checker.workflow_index import (
    FIXED, MARKER, IndexErrorBase, IndexHeaderError, apply_index,
    build_index_files, plan_index, read_index_files, refresh_index,
)


# @trace docs/ru/workflow.md#files,docs/ru/workflow.md#closure,docs/ru/workflow.md#ownership,docs/ru/workflow.md#refresh,docs/ru/codes.md#w7
class WorkflowIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "workflow").mkdir()
        self.pr = Project(self.root, {"workflow": "workflow"})
        self.docs = {}

    def doc(self, prefix, status="", *, closed=None, number=1, result=None, feedback=False):
        directory = {"pln": "plan", "iss": "issue", "dsc": "discussion", "aud": "audit", "adr": "adr"}[prefix]
        path = self.pr.wf / directory
        if prefix != "adr":
            path /= "2024"
        path /= "%s-%03d-tema.md" % (prefix, number)
        header = {K_CREATED: "2024-01-01", K_UPDATED: "2026-01-01"}
        if status:
            header[K_STATUS] = status
        if closed is not None:
            header[K_CLOSED] = closed
        if result:
            header[K_RESULT] = result
        text = "# Тема\n\n" + "\n".join("- %s: %s" % item for item in header.items()) + "\n"
        page = Page(path, text)
        doc = {"id": "%s-%03d" % (prefix, number), "prefix": prefix,
               "num": number, "header": header, "title": "Тема", "page": page,
               "feedback": feedback}
        self.docs[doc["id"]] = doc
        return doc

    def test_every_status_has_one_list_and_counts_are_not_duplicated(self):
        destinations = {"pln": "plans", "iss": "issues", "dsc": "discussions", "adr": "decisions"}
        finals = {"completed", "canceled", "closed", "superseded", "rejected"}
        count = 0
        for prefix, statuses in STATUSES.items():
            for number, status in enumerate(statuses, 1):
                self.doc(prefix, status, number=number, closed="2025-02-03" if status in finals else None)
                count += 1
        self.doc("aud")
        files = build_index_files(self.pr, self.docs)
        self.assertEqual(len(files), 7)
        root = files[self.pr.wf / "INDEX.md"].decode()
        self.assertIn('Total documents: %d.' % (count + 1), root)
        for doc in self.docs.values():
            prefix, status = doc["prefix"], doc["header"].get(K_STATUS)
            name = ("done/2025" if status in finals else
                    "audits" if prefix == "aud" else destinations[prefix])
            destination = self.pr.wf / ("index/%s.md" % name)
            token = "[%s]" % doc["id"].upper()
            self.assertIn(token, files[destination].decode())
            self.assertEqual(sum(token in data.decode() for path, data in files.items()
                                 if path != self.pr.wf / "INDEX.md"), 1)
        self.assertNotIn("[PLN-001]", root)
        self.assertIn("[PLN-002]", root)
        self.assertIn("[PLN-003]", root)

    def test_builder_is_pure_and_closure_year_survives_late_edits(self):
        doc = self.doc("pln", "completed", closed="2024-03-01", result="Готово")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("file read")), \
                patch("subprocess.run", side_effect=AssertionError("Git/history")):
            first = build_index_files(self.pr, self.docs)
            doc["header"][K_UPDATED] = datetime.date.today().isoformat()
            second = build_index_files(self.pr, self.docs)
        self.assertEqual(first, second)
        content = first[self.pr.wf / "index/done/2024.md"].decode()
        self.assertIn("(2024-03-01)", content)
        self.assertEqual(list(self.pr.wf.iterdir()), [])

    def test_invalid_closure_aborts_entire_generation(self):
        for date in (None, "2025-02-30", "2023-12-31", "2999-01-01", "20250101"):
            with self.subTest(date=date):
                self.doc("iss", "closed", closed=date)
                with self.assertRaises(IndexHeaderError):
                    refresh_index(self.pr, self.docs)
                self.assertEqual(list(self.pr.wf.iterdir()), [])
        self.docs.clear()
        self.doc("iss", "superseded")  # чужой статус не становится финальным
        self.assertEqual(len(build_index_files(self.pr, self.docs)), 6)

    def test_feedback_is_not_indexed_or_required_to_have_closure_here(self):
        self.doc("iss", "closed", feedback=True)
        files = build_index_files(self.pr, self.docs)
        self.assertEqual(len(files), 6)
        self.assertNotIn(b"ISS-001", b"".join(files.values()))

    def test_fixed_empty_lists_and_old_empty_year_survive_reopening(self):
        doc = self.doc("dsc", "closed", closed="2025-01-01")
        refresh_index(self.pr, self.docs)
        doc["header"][K_STATUS] = "open"
        plan = refresh_index(self.pr, self.docs)
        year = self.pr.wf / "index/done/2025.md"
        self.assertIn('No closed work items.', year.read_text())
        self.assertNotIn("DSC-001", year.read_text())
        for name in FIXED:
            self.assertIn(self.pr.wf / name, plan.files)
        self.assertIn("DSC-001", (self.pr.wf / "index/discussions.md").read_text())
        times = {path: path.stat().st_mtime_ns for path in plan.files}
        self.assertFalse(refresh_index(self.pr, self.docs).changes)
        self.assertEqual(times, {path: path.stat().st_mtime_ns for path in plan.files})
        doc["header"][K_STATUS], doc["header"][K_CLOSED] = "closed", "2026-01-01"
        refresh_index(self.pr, self.docs)
        self.assertIn("DSC-001", (self.pr.wf / "index/done/2026.md").read_text())
        self.assertNotIn("DSC-001", year.read_text())

    def test_result_links_use_each_destination_depth(self):
        result = ('[local](#done) [doc](../../../docs/a%20b.md#x "title") '
                  '[external](https://example.com/a#x) `[literal](missing.md)` '
                  '[absolute](/docs/a.md) [mail](mailto:a@example.com)')
        self.doc("pln", "completed", closed="2025-01-01", result=result)
        files = build_index_files(self.pr, self.docs)
        year = files[self.pr.wf / "index/done/2025.md"].decode()
        self.assertIn("[local](../../plan/2024/pln-001-tema.md#done)", year)
        self.assertIn('[doc](../../../docs/a%20b.md#x "title")', year)
        self.assertIn('[external](https://example.com/a#x)', year)
        self.assertIn('`[literal](missing.md)`', year)
        self.assertIn('[absolute](/docs/a.md)', year)
        self.assertIn('[mail](mailto:a@example.com)', year)

    def test_unknown_collision_refused_before_any_file_is_written(self):
        path = self.pr.wf / "index/issues.md"
        support.w(path, "# Пользовательская страница\n")
        with self.assertRaises(IndexErrorBase):
            refresh_index(self.pr, self.docs)
        self.assertFalse((self.pr.wf / "INDEX.md").exists())
        self.assertEqual(path.read_text(), "# Пользовательская страница\n")

    def test_unknown_year_and_unrelated_files_are_preserved(self):
        unknown = self.pr.wf / "index/done/2023.md"
        unrelated = self.pr.wf / "index/notes.md"
        support.w(unknown, "# Своя страница\n")
        support.w(unrelated, MARKER + "\n# Не указатель\n")
        plan = refresh_index(self.pr, self.docs)
        self.assertNotIn(unknown, plan.files)
        self.assertNotIn(unrelated, plan.files)
        self.assertEqual(unknown.read_text(), "# Своя страница\n")
        self.doc("pln", "completed", closed="2025-01-01")
        occupied = self.pr.wf / "index/done/2025.md"
        support.w(occupied, "# Своя страница\n")
        with self.assertRaises(IndexErrorBase):
            refresh_index(self.pr, self.docs)

    def test_index_with_marker_can_be_replaced_and_user_index_is_preserved(self):
        path = self.pr.wf / "INDEX.md"
        handwritten = "# Указатель рабочих материалов\n\n## Список проекта\n"
        support.w(path, handwritten)
        with self.assertRaises(IndexErrorBase):
            refresh_index(self.pr, self.docs)
        self.assertEqual(path.read_text(), handwritten)
        support.w(path, MARKER + "\nРучная правка\n")
        refresh_index(self.pr, self.docs)
        self.assertNotIn("Ручная правка", path.read_text())

    def test_symlink_file_directory_and_workflow_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        path = self.pr.wf / "index"
        path.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(IndexErrorBase):
            refresh_index(self.pr, self.docs)
        self.assertEqual(list(outside.iterdir()), [])
        path.unlink()
        target = self.root / "target.md"
        target.write_text("mine")
        path = self.pr.wf / "INDEX.md"
        path.symlink_to(target)
        with self.assertRaises(IndexErrorBase):
            refresh_index(self.pr, self.docs)
        self.assertEqual(target.read_text(), "mine")
        path.unlink()
        self.pr.wf.rmdir()
        self.pr.wf.symlink_to(outside, target_is_directory=True)
        project = Project(self.root, {"workflow": "workflow"})
        with self.assertRaises(IndexErrorBase):
            refresh_index(project, {})

    def test_write_failure_and_interruption_restore_every_file_and_directory(self):
        for failure in (OSError("disk failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                path = self.pr.wf / "INDEX.md"
                support.w(path, MARKER + "\nold\n")
                previous = read_index_files(self.pr)
                files = build_index_files(self.pr, self.docs, previous=previous)
                plan = plan_index(self.pr, files, previous=previous)
                calls = []

                def fail_after_write(destination, content):
                    destination.write_bytes(content)
                    calls.append(destination)
                    if len(calls) == 3:
                        raise failure

                with patch("lipi.checker.workflow_index._write_file", side_effect=fail_after_write):
                    with self.assertRaises(type(failure)):
                        apply_index(self.pr, plan)
                self.assertEqual(read_index_files(self.pr), previous)
                self.assertFalse((self.pr.wf / "index").exists())

    def test_cache_refresh_and_git_index_unchanged(self):
        support.run(["git", "init", "-q", str(self.root)])
        path = self.pr.wf / "INDEX.md"
        support.w(path, MARKER + "\nold\n")
        support.run(["git", "add", "."], cwd=self.root)
        before = (self.root / ".git/index").read_bytes()
        self.pr = Project(self.root, {"workflow": "workflow"})
        old = self.pr.page(path)
        refresh_index(self.pr, self.docs)
        self.assertIsNot(self.pr.page(path), old)
        self.assertIn('Workflow index', self.pr.page(path).text)
        self.assertEqual((self.root / ".git/index").read_bytes(), before)

    def test_runner_ci_reports_each_file_and_local_refreshes_before_links(self):
        support.w(self.root / "lipi.json", json.dumps({"workflow": "workflow"}))
        refresh_index(self.pr, self.docs)
        first = self.pr.wf / "INDEX.md"
        second = self.pr.wf / "index/plans.md"
        support.w(first, MARKER + "\n[old](missing.md)\n")
        support.w(second, MARKER + "\nold\n")
        before = read_index_files(self.pr)
        env = dict(os.environ, CI="1")
        code, output = support.check(self.root, "--format", "json", env=env)
        data = json.loads(output)
        findings = data["errors"] + data["warnings"]
        self.assertEqual({item["file"] for item in findings if item["code"] == "W7"},
                         {"workflow/INDEX.md", "workflow/index/plans.md"})
        self.assertEqual(read_index_files(self.pr), before)
        env.pop("CI", None)
        code, output = support.check(self.root, "--format", "json", "--structure", env=env)
        data = json.loads(output)
        self.assertFalse([item for item in data["errors"] + data["warnings"]
                          if item["code"] in ("W6", "W7")], output)
        self.assertNotIn("missing.md", json.dumps(data))
        node_ids = {node["id"] for node in data["structure"]["nodes"]}
        self.assertTrue({"workflow/" + name for name in FIXED}.issubset(node_ids))

    def test_runner_nonwriting_modes_preserve_bytes_and_git_index(self):
        support.w(self.root / "lipi.json", '{"workflow": "workflow"}\n')
        refresh_index(self.pr, self.docs)
        support.git_init(self.root)
        self.assertEqual(support.commit(self.root)[0], 0)
        support.w(self.pr.wf / "INDEX.md", MARKER + "\nold\n")
        before = read_index_files(self.pr)
        git_index = (self.root / ".git/index").read_bytes()
        for args in (("--format", "github"), ("--staged",), ("--diff", "HEAD")):
            with self.subTest(args=args):
                code, output = support.check(self.root, *args)
                self.assertIn("W7", output)
                self.assertEqual(read_index_files(self.pr), before)
                self.assertEqual((self.root / ".git/index").read_bytes(), git_index)

    def test_runner_bad_closure_reports_header_without_partial_index(self):
        support.w(self.root / "lipi.json", '{"workflow": "workflow"}\n')
        for closed, code in ((None, "W4"), ("2025-02-30", "W3")):
            with self.subTest(closed=closed):
                doc = self.doc("pln", "completed", closed=closed, result="Готово")
                support.w(doc["page"].path, doc["page"].text)
                status, output = support.check(self.root, "--write-index", "--format", "json")
                data = json.loads(output)
                self.assertTrue(any(item["code"] == code for item in data["errors"]), output)
                self.assertFalse(any(item["code"] == "W7" for item in data["errors"]), output)
                self.assertFalse((self.pr.wf / "INDEX.md").exists())
                self.assertFalse((self.pr.wf / "index").exists())


if __name__ == "__main__":
    unittest.main()
