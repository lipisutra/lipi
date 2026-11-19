"""The same Markdown region drives drift, history and slice."""
import json
import sys
import unittest
from pathlib import Path

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))


FORMS = {
    "heading": ('## Rule <a id="target"></a>\n\nOwn text.\n\n'
                '### Child <a id="child"></a>\n\nOwn detail.\n\n'
                '## Boundary\n\nNeighbor text.\n', "Own detail."),
    "paragraph": ('Own first line.\n<a id="target"></a> Own text.\n'
                  'Own continuation.\n\nNeighbor text.\n', "Own continuation."),
    "item": ('- <a id="target"></a> Own text.\n  Own continuation.\n'
             '  - Own detail.\n- Neighbor text.\n', "Own detail."),
    "row": ('| Key | Meaning |\n| --- | --- |\n| Earlier | Neighbor text. |\n'
            '| <a id="target"></a> Own | Own text. |\n| Later | Neighbor text. |\n',
            "Own text."),
    "header": ('| Key | Meaning |\n| --- | --- |\n| Earlier | Neighbor text. |\n'
               '| <a id="target"></a> Own | Own text. |\n| Later | Neighbor text. |\n',
               "Meaning"),
}


class AnchorRegionBoundaries(unittest.TestCase):
    def test_exact_line_sets_for_each_markdown_form(self):
        from lipi.checker.model import Page, anchor_region

        cases = [
            ("heading-sibling", '## Own <a id="target"></a>\nBody.\n'
             '### Child <a id="child"></a>\nDetail.\n## Stop\nNeighbor.\n', (1, 2, 3, 4)),
            ("heading-ancestor", '### Own <a id="target"></a>\nBody.\n'
             '#### Child\nDetail.\n## Stop\nNeighbor.\n', (1, 2, 3, 4)),
            ("heading-fence-no-final-newline", '## Own <a id="target"></a>\n'
             '```\n## Fake boundary\n```', (1, 2, 3, 4)),
            ("paragraph", 'Before.\n\nOwn first.\n<a id="target"></a> Own second.\n'
             'Own last.\n\nNeighbor.\n', (3, 4, 5)),
            ("bullet", '- <a id="target"></a> Own.\n  Continued.\n'
             '  - Nested.\n- Neighbor.\n', (1, 2, 3)),
            ("numbered", '1. <a id="target"></a> Own.\n   Continued.\n'
             '   1. Nested.\n2. Neighbor.\n', (1, 2, 3)),
            ("item-paragraph", '- <a id="target"></a> Own.\n\n'
             '  Continued.\n\nNeighbor paragraph.\n', (1, 2, 3)),
            ("row", '| Key | Meaning |\n| --- | --- |\n| Earlier | Neighbor |\n'
             '| Middle | Another |\n| <a id="target"></a> Own | Stable |\n'
             '| Later | Neighbor |\n', (1, 5)),
        ]
        for name, text, expected in cases:
            with self.subTest(form=name):
                page = Page(Path("guide.md"), text)
                self.assertEqual(anchor_region(page, page.anchors["target"]), expected)


class AnchorRegionIntegration(support.Case):
    def prepare(self):
        root = self.project()
        for name, (body, _) in FORMS.items():
            support.w(root / "docs" / (name + ".md"), "# " + name + "\n\n" + body)
            support.w(root / "src" / (name + ".py"),
                      "# %s docs/%s.md#target\nvalue = 1\n" % (support.TAG, name))
            support.sub(root / "docs" / "README.md", "| --- | --- |",
                        "| --- | --- |\n| %s | [%s](%s.md#target) |" % (name, name, name))
        support.git_init(root)
        self.commit(root, 1)
        return root

    def commit(self, root, day):
        code, out = support.commit(root, date="2026-01-%02dT09:00:00+00:00" % day)
        self.assertEqual(code, 0, out)

    def change_code(self, root):
        for name in FORMS:
            support.sub(root / "src" / (name + ".py"), "value = 1", "value = 2")

    def change_docs(self, root, own):
        for name, (_, own_text) in FORMS.items():
            text = own_text if own else "Neighbor text."
            support.sub(root / "docs" / (name + ".md"), text, text + " Revised.")

    def assert_findings(self, root, check, expected, *args):
        if check == "T2":
            args += ("--structure",)
        code, result = support.check_json(root, *args)
        self.assertEqual(code, 0, result)
        findings = result["errors"] + result["warnings"]
        actual = {item["subject"] for item in findings if item["code"] == check}
        if check == "T2":
            self.assertEqual({item["anchor"] for item in result["structure"]["stale"]}, actual)
        for name in FORMS:
            with self.subTest(check=check, form=name, expected=expected):
                target = "docs/" + name + ".md#target"
                self.assertEqual(target in actual, expected, findings)
                if check == "A4" and expected:
                    message = next(item["message"] for item in findings
                                   if item["code"] == check and item["subject"] == target)
                    self.assertIn("2026-01-01T09:00:00+00:00", message)
                    self.assertIn("2026-01-02T09:00:00+00:00", message)

    def assert_slice_staleness(self, root, expected):
        # Query each target to verify both the signal and checked accounting.
        for name in FORMS:
            with self.subTest(form=name, stale=expected):
                code, out = support.cli(root, "slice", "docs/" + name + ".md#target",
                                        "--format", "json", "--full")
                self.assertEqual(code, 0, out)
                result = json.loads(out)
                self.assertEqual(result["checks"]["staleness"],
                                 {"state": "full", "checked": 1, "total": 1})
                signals = [item for block in result["blocks"] if block["kind"] == "signals"
                           for item in block["items"] if item["code"] == "A4"]
                self.assertEqual([item["path"] for item in signals],
                                 ["src/" + name + ".py"] if expected else [], result)

    def test_staged_neighbor_edits_do_not_refresh_the_target(self):
        root = self.prepare()
        self.change_code(root)
        self.change_docs(root, own=False)
        self.assertEqual(support.git(root, "add", "-A")[0], 0)
        self.assert_findings(root, "T2", True, "--staged")
        self.change_docs(root, own=True)
        self.assertEqual(support.git(root, "add", "-A")[0], 0)
        self.assert_findings(root, "T2", False, "--staged")

    def test_dated_neighbor_then_own_edits_agree_for_diff_audit_and_slice(self):
        root = self.prepare()
        self.change_code(root)
        self.commit(root, 2)
        self.change_docs(root, own=False)
        self.commit(root, 3)
        self.assert_findings(root, "T2", True, "--diff", "HEAD~2...HEAD")
        self.assert_findings(root, "A4", True, "--audit")
        self.assert_slice_staleness(root, True)
        self.change_docs(root, own=True)
        self.commit(root, 4)
        self.assert_findings(root, "T2", False, "--diff", "HEAD~3...HEAD")
        self.assert_findings(root, "A4", False, "--audit")
        self.assert_slice_staleness(root, False)

    def test_staged_deletion_uses_the_deleted_region_not_the_preceding_line(self):
        root = self.prepare()
        deletions = {
            "row": "| Later | Neighbor text. |\n",
            "item": "- Neighbor text.\n",
            "paragraph": "Own continuation.\n",
        }
        for name, deleted in deletions.items():
            support.sub(root / "src" / (name + ".py"), "value = 1", "value = 2")
            support.sub(root / "docs" / (name + ".md"), deleted, "")
        self.assertEqual(support.git(root, "add", "-A")[0], 0)
        for args in (("--staged",), ("--diff", "HEAD~1...HEAD")):
            if args[0] == "--diff":
                self.commit(root, 2)
            code, result = support.check_json(root, *args, "--structure")
            self.assertEqual(code, 0, result)
            actual = {item["subject"] for item in result["warnings"] if item["code"] == "T2"}
            self.assertEqual({item["anchor"] for item in result["structure"]["stale"]}, actual)
            for name in deletions:
                with self.subTest(form=name, mode=args[0]):
                    self.assertEqual("docs/" + name + ".md#target" in actual,
                                     name != "paragraph", result["warnings"])


if __name__ == "__main__":
    unittest.main()
