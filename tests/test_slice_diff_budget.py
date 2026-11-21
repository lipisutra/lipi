"""Budget and filter boundaries for the two versions of changed contracts."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests import support

from lipi.slice_output import select_response


def block(kind, items):
    return {"kind": kind, "items": items, "omitted": 0, "hint": []}


def response(sections, *blocks):
    return {"target": {"kind": "diff"}, "blocks": list(blocks), "incomplete": False,
            "checks": {"diff": {"sections": sections, "unanchored": 1}}}


def section(anchor, before, after):
    return {"target": "docs/export.md#" + anchor, "before": before, "after": after}


# @trace docs/ru/slice-output.md#budget,docs/ru/slice-diff.md#json
class SliceDiffBudget(unittest.TestCase):
    def test_shared_cap_rounds_preserve_section_order_and_absent_sides(self):
        paired = section("fields", "Fields\nOld value", "Fields\nNew value")
        added = section("order", None, "Order\nTwo fields")
        removed = section("size", "Size\nOne byte", None)
        source = response([paired, added, removed])
        original = copy.deepcopy(source)

        for budget, expected, hidden in (
            (1, [{**paired, "before": "Old value", "after": "",
                  "omitted": {"before": 1, "after": 2}}], 2),
            (6, [{**paired, "before": "Old value", "after": "New value",
                  "omitted": {"before": 1, "after": 1}}], 2),
            (9, [{**paired, "before": "Old value", "after": "New value",
                  "omitted": {"before": 1, "after": 1}},
                 {**added, "after": "Order", "omitted": {"before": 0, "after": 1}}], 1),
            (12, [{**paired, "before": "Old value", "after": "New value",
                   "omitted": {"before": 1, "after": 1}},
                  {**added, "after": "Order", "omitted": {"before": 0, "after": 1}},
                  {**removed, "before": "Size", "omitted": {"before": 1, "after": 0}}], None),
            (15, [{**paired, "after": "New value", "omitted": {"before": 0, "after": 1}},
                  {**added, "after": "Order", "omitted": {"before": 0, "after": 1}},
                  {**removed, "before": "Size", "omitted": {"before": 1, "after": 0}}], None),
            (24, [paired, added, removed], None),
        ):
            with self.subTest(budget=budget):
                selected = select_response(source, budget=budget)
                diff = selected["checks"]["diff"]
                self.assertEqual(diff["sections"], expected)
                if hidden is None:
                    self.assertNotIn("sections_omitted", diff)
                else:
                    self.assertEqual(diff["sections_omitted"], hidden)
                self.assertEqual(selected["blocks"], [])
                self.assertEqual(selected["incomplete"], budget < 24)
                self.assertEqual(source, original)

    def test_signals_share_total_budget_and_full_frees_excerpt_lines(self):
        paired = section("fields", "Heading\nOld\nBefore note", "Heading\nNew\nAfter note")
        signals = [{"level": "warning"} for _ in range(5)] + [{"level": "info"} for _ in range(4)]
        source = response([paired], block("signals", signals), block("tests", [{"id": 1}]))

        tiny = select_response(source, budget=1)
        self.assertEqual(tiny["checks"]["diff"]["sections"], [])
        self.assertEqual(tiny["checks"]["diff"]["sections_omitted"], 1)
        self.assertEqual(tiny["blocks"][0]["items"], signals[:1])

        limited = select_response(source, budget=9)
        self.assertEqual(limited["checks"]["diff"]["sections"], [
            {**paired, "before": "Old", "after": "New", "omitted": {"before": 2, "after": 2}},
        ])
        self.assertEqual([len(group["items"]) for group in limited["blocks"]], [7, 0])
        self.assertTrue(limited["incomplete"])

        full = select_response(source, budget=9, full=True)
        self.assertEqual(full["checks"]["diff"]["sections"], [paired])
        self.assertNotIn("sections_omitted", full["checks"]["diff"])
        self.assertEqual([len(group["items"]) for group in full["blocks"]], [8, 1])
        self.assertTrue(full["incomplete"])

    def test_only_filters_sections_without_recording_an_omission(self):
        paired = section("fields", "Old", "New")
        source = response([paired], block("code", [{"id": 1}]))
        for full in (False, True):
            with self.subTest(full=full):
                filtered = select_response(source, budget=1, full=full, only=["code"])
                self.assertEqual(filtered["checks"]["diff"], {"unanchored": 1})
                self.assertFalse(filtered["incomplete"])
                self.assertEqual(filtered["blocks"], source["blocks"])

        excerpt = select_response(source, budget=6, only="excerpt")
        self.assertEqual(excerpt["checks"]["diff"]["sections"], [paired])
        self.assertFalse(excerpt["incomplete"])
        self.assertEqual(excerpt["blocks"], [])

        full = select_response(source, budget=1, full=True)
        self.assertEqual(full["checks"]["diff"]["sections"], [paired])
        self.assertEqual(full["blocks"], source["blocks"])
        self.assertFalse(full["incomplete"])

    def test_insertions_and_deletions_put_changed_text_before_context(self):
        start = "Heading\n\n" + "\n".join("Field %d has a value." % n for n in range(20))
        end = "\n\nForm fields are ordered by their identifier.\n"
        added = "Export the checksum last."
        insertion = section("fields", start + end, start + "\n" + added + end)
        deletion = section("fields", insertion["after"], insertion["before"])
        for change, before, after, omitted in (
            (insertion, "", added, {"before": 25, "after": 25}),
            (deletion, added, "", {"before": 25, "after": 25}),
        ):
            with self.subTest(change=change):
                tiny = select_response(response([change]), budget=1)
                self.assertEqual(tiny["checks"]["diff"]["sections"], [
                    section("fields", before, after) | {"omitted": omitted},
                ])

        limited = select_response(response([insertion]), budget=6)
        displayed, = limited["checks"]["diff"]["sections"]
        self.assertEqual(displayed["before"], "Field 19 has a value.")
        self.assertEqual(displayed["after"], added)
        self.assertEqual(displayed["omitted"], {"before": 24, "after": 25})

    def test_blank_line_edit_keeps_visible_context_on_both_sides(self):
        paired = section("fields", "Heading\nKeep the fields in order.",
                         "Heading\n\nKeep the fields in order.")
        selected = select_response(response([paired]), budget=6)
        self.assertEqual(selected["checks"]["diff"]["sections"], [
            section("fields", "Heading", "Heading") | {"omitted": {"before": 1, "after": 2}},
        ])

    def test_git_diff_prioritizes_changed_wording_in_long_markdown_section(self):
        path = "docs/export.md"
        title = '# Export\n\n## Record fields <a id="fields"></a>\n\n'
        context = "".join("Field %d is optional.\n" % n for n in range(40))
        suffix = "\n" + "Keep optional fields in the original order.\n" * 220
        old = "Write the name before the identifier."
        new = "Write the identifier before the name."
        with tempfile.TemporaryDirectory(prefix="lipi-diff-budget-") as temp:
            root = Path(temp)
            support.w(root / "lipi.json", '{"slice_budget": 6}\n')
            support.w(root / path, title + context + old + "\n" + suffix)
            support.git_init(root)
            code, out = support.commit(root)
            self.assertEqual(code, 0, out)
            support.w(root / path, title + context + new + "\n" + suffix)
            code, out = support.git(root, "add", "--", path)
            self.assertEqual(code, 0, out)

            for mode in (("--diff", "HEAD"), ("--staged",)):
                with self.subTest(mode=mode):
                    code, out = support.cli(root, "slice", *mode, "--format", "json")
                    self.assertEqual(code, 0, out)
                    result = json.loads(out)
                    displayed, = result["checks"]["diff"]["sections"]
                    self.assertEqual(displayed, {**section("fields", old, new),
                                                 "linked": False,
                                                 "omitted": {"before": 263, "after": 263}})
                    self.assertTrue(result["incomplete"])
                    self.assertNotIn("sections_omitted", result["checks"]["diff"])


if __name__ == "__main__":
    unittest.main()
