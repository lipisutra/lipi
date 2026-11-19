"""A7 — открытые обсуждения решений, A8 — срок работы."""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))

from lipi.checker.audit import audit
from lipi.checker.config import load_config
from lipi.checker.model import Project
from lipi.checker.report import Report, level_of_project
from lipi.checker.workflow import check_workflow, scan_workflow


class FixedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 18)


class WorkAuditTests(support.Case):
    def audit_findings(self, root, code):
        root = root.resolve()
        cfg = load_config(root, None)
        pr = Project(root, cfg)
        rep = Report(level_of_project(cfg))
        docs, others = scan_workflow(pr, rep)
        check_workflow(pr, rep, docs, others)
        with patch("lipi.checker.audit.datetime.date", FixedDate):
            audit(pr, rep, docs, {}, {}, {})
        return [item for item in rep.items if item[3] == code]

    def set_header(self, root, prefix, fields):
        fields = dict(fields)
        due = fields.pop("Due", None)
        support.header_set(root, prefix, fields)
        if due is not None:
            support.sub(support.doc(root, prefix), "- Created:",
                        "- Due: %s\n- Created:" % due)

    def work(self, path, status, body=""):
        closed = ("- Closed: 2026-11-18\n"
                  if status in ("closed", "superseded", "rejected") else "")
        support.w(path, "# Работа\n\n- Created: 2026-11-18\n"
                  "- Updated: 2026-11-18\n%s- Status: %s\n\n%s\n"
                  % (closed, status, body))
        return path

    def decision_and_discussion(self, root):
        discussion = self.work(root / "workflow/discussion/2026/dsc-001-topic.md",
                               "open", '## Вопрос <a id="question"></a>\n\nТекст.')
        decision = self.work(root / "workflow/adr/adr-001-choice.md", "accepted",
                             "[Обсуждение](../discussion/2026/dsc-001-topic.md#question)")
        return decision, discussion

    def test_a7_links_are_deduplicated_per_decision_discussion(self):
        root = self.project()
        decision, _ = self.decision_and_discussion(root)
        with decision.open("a") as stream:
            stream.write("[Повтор](../discussion/2026/dsc-001-topic.md)\n")
        second = self.work(root / "workflow/adr/adr-002-choice.md", "accepted",
                           "[Обсуждение](../discussion/2026/dsc-001-topic.md)")
        findings = self.audit_findings(root, "A7")
        self.assertEqual(len(findings), 2, findings)
        self.assertEqual({item[0] for item in findings},
                         {str(p.relative_to(root)) for p in (decision, second)})
        for item in findings:
            self.assertEqual(item[2], "W")
            self.assertEqual(item[5], "dsc-001")
            self.assertIn(support.localized('Check whether the discussion can be closed', "проверьте, можно ли закрыть обсуждение"), item[4])
            self.assertGreater(item[1], 0)

    def test_a7_requires_accepted_decision_open_discussion_and_real_link(self):
        cases = [(status, "open", True) for status in
                 ("proposed", "superseded", "rejected", "неизвестно")]
        cases += [("accepted", "closed", True), ("accepted", "open", False)]
        for decision_status, discussion_status, link in cases:
            with self.subTest(decision=decision_status, discussion=discussion_status, link=link):
                root = self.project()
                decision, discussion = self.decision_and_discussion(root)
                self.work(discussion, discussion_status)
                body = ("[Обсуждение](../discussion/2026/dsc-001-topic.md)" if link else
                        "DSC-001\n`[пример](../discussion/2026/dsc-001-topic.md)`\n"
                        "```md\n[пример](../discussion/2026/dsc-001-topic.md)\n```\n"
                        "[внешнее](https://example.test/dsc-001-topic.md)")
                self.work(decision, decision_status, body)
                self.assertEqual(self.audit_findings(root, "A7"), [])

    def test_a7_configured_decisions_and_external_workflow(self):
        root = self.project()
        external = root.parent / (root.name + "-workflow")
        (root / "workflow").rename(external)
        decisions = root / "decisions"
        support.set_config(root, workflow=str(external), decisions="decisions")
        discussion = self.work(external / "discussion/2026/dsc-001-topic.md", "open")
        decision = decisions / "0001-choice.md"
        link = os.path.relpath(discussion, decision.parent)
        self.work(decision, "accepted", "[Обсуждение](%s)" % link)
        findings = self.audit_findings(root, "A7")
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0][0], "decisions/0001-choice.md")
        self.assertEqual(findings[0][5], "dsc-001")

    def test_a8_deadline_matrix_for_active_plans_and_issues(self):
        for prefix, statuses in (("pln", ("new", "in progress", "pending acceptance", "deferred")),
                                 ("iss", ("open", "in progress"))):
            for status in statuses:
                for due, expected in ((None, False), ("2026-11-17", True),
                                      ("2026-11-18", False), ("2026-11-19", False)):
                    with self.subTest(prefix=prefix, status=status, due=due):
                        root = self.project()
                        fields = {"Status": status}
                        if due is not None:
                            fields["Due"] = due
                        self.set_header(root, prefix, fields)
                        findings = self.audit_findings(root, "A8")
                        self.assertEqual(len(findings), int(expected), findings)
                        if expected:
                            self.assertEqual(findings[0][2], "W")
                            self.assertEqual(findings[0][5], prefix + "-001")
                            self.assertIn(due, findings[0][4])

    def test_a8_invalid_calendar_date_is_header_warning(self):
        for due in ("", "2026-02-29", "2024-02-30", "2026-13-01", "0000-01-01",
                    "2026-1-01", "20261117", "2026-W47-2", "завтра"):
            with self.subTest(due=due):
                root = self.project()
                self.set_header(root, "iss", {"Due": due})
                findings = self.audit_findings(root, "A8")
                self.assertEqual(len(findings), 1, findings)
                self.assertEqual(findings[0][2], "W")
                self.assertEqual(findings[0][5], "Due")
                self.assertIn(support.localized('header', "в шапке"), findings[0][4])
        root = self.project()
        self.set_header(root, "iss", {"Due": "2024-02-29"})
        findings = self.audit_findings(root, "A8")
        self.assertEqual(findings[0][5], "iss-001")  # високосная дата валидна

    def test_a8_final_unknown_statuses_and_other_types_are_ignored(self):
        cases = [("pln", status) for status in ("completed", "canceled", "неизвестно", "")]
        cases += [("iss", status) for status in ("closed", "неизвестно", "")]
        cases += [("dsc", "open"), ("adr", "accepted"), ("aud", "")]
        for prefix, status in cases:
            for due in ("2026-11-17", "не дата"):
                with self.subTest(prefix=prefix, status=status, due=due):
                    root = self.project()
                    if prefix not in ("pln", "iss"):
                        directory = root / "workflow" / support.TYPE_DIRS[prefix]
                        if prefix != "adr":
                            directory /= "2026"
                        self.work(directory / (prefix + "-001-topic.md"), status)
                    fields = {"Status": status, "Due": due}
                    if status in ("completed", "canceled", "closed"):
                        fields["Closed"] = datetime.date.today().isoformat()
                    self.set_header(root, prefix, fields)
                    self.assertEqual(self.audit_findings(root, "A8"), [])

    def test_a7_a8_only_audit_and_configurable_levels(self):
        root = self.project()
        self.decision_and_discussion(root)
        self.set_header(root, "iss", {"Due": "не дата"})
        support.reindex(root)
        code, data = support.check_json(root)
        self.assertEqual(code, 0, data)
        self.assertFalse(any(item["code"] in ("A7", "A8", "W3")
                             for item in data["errors"] + data["warnings"]), data)
        for level, expected_code, group in (("warning", 0, "warnings"),
                                           ("error", 1, "errors"), ("off", 0, None)):
            with self.subTest(level=level):
                support.set_config(root, codes={"A7": level, "A8": level})
                code, data = support.check_json(root, "--audit")
                self.assertEqual(code, expected_code, data)
                for finding_code in ("A7", "A8"):
                    findings = [item for item in data["errors"] + data["warnings"]
                                if item["code"] == finding_code]
                    self.assertEqual(len(findings), int(group is not None), data)
                    if group:
                        self.assertIn(findings[0], data[group])


if __name__ == "__main__":
    unittest.main()
