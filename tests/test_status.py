"""T3: статус цели у метки кода и covers, уровни и базовая линия.

Запуск: python3 -m unittest tests.test_status -v
"""
import json
import unittest

from tests import support


# @trace docs/ru/codes.md#t3,ADR-013
class TargetStatusChecks(support.Case):
    base_args = ("--type", "app")

    def work(self, root, prefix, status=None, num=100, result="Работа закончена."):
        directory = root / "workflow" / support.TYPE_DIRS[prefix]
        if prefix != "adr":
            directory /= "2026"
        path = directory / ("%s-%03d-test.md" % (prefix, num))
        final = {"adr": ("superseded", "rejected"), "pln": ("completed", "canceled"),
                 "iss": ("closed",), "dsc": ("closed",)}
        support.w(path, "# Работа для проверки\n\n"
                  "- Created: 2026-01-01\n"
                  "- Updated: 2026-01-01\n"
                  + ("- Status: %s\n" % status if status is not None else "")
                  + ("- Closed: 2026-01-01\n" if status in final.get(prefix, ()) else "")
                  + "- Kind: bug\n- Result: %s\n\n" % result
                  + "## Observation\n\nТекст.\n\n"
                  "## Purpose\n\nТекст.\n\n"
                  "## Completion criteria\n\nТекст.\n\n"
                  '## Раздел <a id="section"></a>\n\nТекст.\n')
        return "%s-%03d" % (prefix.upper(), num), path

    def link(self, root, kind, targets):
        if kind == "trace":
            path = root / "src/extra.py"
            support.w(path, "".join("# %s %s\n" % (support.TAG, target) for target in targets))
            first_line = 1
        else:
            path = root / "docs/help.md"
            support.w(path, "# Справка\n\n" + "".join(
                "<!-- covers: %s -->\n" % target for target in targets))
            support.sub(root / "docs/README.md", "| --- | --- |",
                        "| --- | --- |\n| Справка | [Справка](help.md) |")
            first_line = 3
        return path.relative_to(root).as_posix(), first_line

    def check(self, root, expected=0):
        support.reindex(root)
        code, data = support.check_json(root)
        self.assertIsNotNone(data)
        self.assertEqual(code, expected, data)
        return data

    def findings(self, data, code="T3"):
        return [item for level in ("errors", "warnings") for item in data[level]
                if item["code"] == code]

    def test_status_matrix_for_both_links(self):
        """Все допустимые статусы: только завершённые основания дают T3."""
        statuses = {
            "adr": ("proposed", "accepted", "superseded", "rejected"),
            "iss": ("open", "in progress", "closed"),
            "pln": ("new", "in progress", "pending acceptance", "deferred", "completed", "canceled"),
            "dsc": ("open", "closed"),
            "aud": (None, "closed"),
        }
        actions = {
            ("adr", "superseded"): 'check the code against the new decision',
            ("adr", "rejected"): 'remove the dependency on the rejected decision',
            ("iss", "closed"): 'check whether the link is needed. Remove it if it was a temporary workaround.',
            ("pln", "completed"): 'check whether the link to the completed plan is still relevant',
            ("pln", "canceled"): 'remove the dependency on the canceled plan',
            ("dsc", "closed"): 'check the link against the discussion outcome',
        }
        for kind in ("trace", "covers"):
            with self.subTest(kind=kind):
                root = self.project()
                targets, expected = [], {}
                for prefix, values in statuses.items():
                    for num, status in enumerate(values, 100):
                        target, _ = self.work(root, prefix, status, num)
                        targets.append(target)
                        if (prefix, status) in actions:
                            expected[target + " " + status] = (len(targets) - 1, actions[prefix, status])
                source, first_line = self.link(root, kind, targets)
                data = self.check(root)
                self.assertEqual(data["errors"], [])
                findings = self.findings(data)
                self.assertEqual(len(findings), len(expected), data)
                self.assertEqual({item["subject"] for item in findings}, set(expected))
                for item in findings:
                    offset, action = expected[item["subject"]]
                    self.assertIn(item, data["warnings"])
                    self.assertEqual((item["file"], item["line"]), (source, first_line + offset))
                    self.assertEqual(item["message"], item["subject"] + " — " + action)

    def test_markdown_section_has_no_status(self):
        """Даже раздел закрытого рабочего документа не является статусной целью."""
        for kind in ("trace", "covers"):
            with self.subTest(kind=kind):
                root = self.project()
                _, path = self.work(root, "iss", "closed")
                self.link(root, kind, [path.relative_to(root).as_posix() + "#section"])
                self.assertEqual(self.findings(self.check(root)), [])

    def test_configured_levels_for_both_links(self):
        for kind in ("trace", "covers"):
            for level in ("off", "error", "warning"):
                with self.subTest(kind=kind, level=level):
                    root = self.project()
                    target, _ = self.work(root, "iss", "closed")
                    self.link(root, kind, [target])
                    support.set_config(root, codes={"T3": level})
                    data = self.check(root, 1 if level == "error" else 0)
                    findings = self.findings(data)
                    self.assertEqual(len(findings), 0 if level == "off" else 1, data)
                    if findings:
                        self.assertIn(findings[0], data["errors" if level == "error" else "warnings"])

    def test_replacement_uses_first_work_link_in_result(self):
        """Номер в тексте и label не определяют преемника: решает адрес ссылки."""
        for kind in ("trace", "covers"):
            with self.subTest(kind=kind):
                root = self.project()
                _, successor = self.work(root, "pln", "new", 101)
                _, later = self.work(root, "adr", "accepted", 102)
                target, _ = self.work(root, "adr", "superseded", result=(
                    "ADR-999; [описание](../../docs/guide.md); [ADR-777](../plan/2026/%s#section); "
                    "[другое решение](%s)." % (successor.name, later.name)))
                self.link(root, kind, [target])
                findings = self.findings(self.check(root))
                self.assertEqual(len(findings), 1)
                self.assertIn("ADR-100 superseded PLN-101", findings[0]["message"])
                for wrong in ("ADR-999", "ADR-777", "ADR-102"):
                    self.assertNotIn(wrong, findings[0]["message"])

    def test_replacement_without_work_link(self):
        """Итог без рабочей ссылки не создаёт вымышленного преемника или ошибку."""
        for kind in ("trace", "covers"):
            with self.subTest(kind=kind):
                root = self.project()
                target, _ = self.work(root, "adr", "superseded", result="Заменено ADR-999.")
                self.link(root, kind, [target])
                data = self.check(root)
                self.assertEqual(data["errors"], [])
                findings = self.findings(data)
                self.assertEqual(len(findings), 1)
                self.assertIn('check the code against the new decision', findings[0]["message"])
                self.assertNotIn("ADR-999", findings[0]["message"])

    def test_missing_unknown_or_wrong_type_status_is_w3_only(self):
        for kind in ("trace", "covers"):
            for status in (None, "неизвестно", "closed"):
                with self.subTest(kind=kind, status=status):
                    root = self.project()
                    target, _ = self.work(root, "adr", status)
                    self.link(root, kind, [target])
                    data = self.check(root, 1)
                    self.assertTrue(self.findings(data, "W3"), data)
                    self.assertEqual(self.findings(data), [])

    def test_workflow_disabled_has_resolution_error_only(self):
        for kind, code in (("trace", "T1"), ("covers", "D6")):
            with self.subTest(kind=kind):
                root = self.project()
                target, _ = self.work(root, "iss", "closed")
                self.link(root, kind, [target])
                support.set_config(root, workflow=None)
                data = self.check(root, 1)
                self.assertTrue(self.findings(data, code), data)
                self.assertEqual(self.findings(data), [])

    def test_baseline_keeps_status_as_part_of_subject(self):
        """При T3:error новое основание не поглощается линией старого статуса."""
        for kind in ("trace", "covers"):
            with self.subTest(kind=kind):
                root = self.project()
                target, path = self.work(root, "adr", "rejected")
                source, _ = self.link(root, kind, [target])
                support.set_config(root, codes={"T3": "error"})
                self.check(root, 1)
                code, out = support.check(root, "baseline")
                self.assertEqual(code, 0, out)
                entries = json.loads((root / support.BASE_REL).read_text(encoding="utf-8"))["entries"]
                self.assertEqual(entries, [{"code": "T3", "file": source,
                                           "subject": "ADR-100 rejected", "count": 1}])
                known = self.check(root)
                self.assertEqual(self.findings(known), [])
                self.assertEqual(known["baseline"]["known"], 1)
                support.sub(path, "- Status: rejected", "- Status: superseded")
                changed = self.check(root, 1)
                self.assertEqual([item["subject"] for item in self.findings(changed)],
                                 ["ADR-100 superseded"])


if __name__ == "__main__":
    unittest.main()
