"""Black-box contract of slice: real CLI, isolated projects, no checker mocks."""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests import support


TARGET = "docs/pricing.md#threshold"


class SliceContract(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("lipi.json", "{}\n")

    def write(self, path, text):
        support.w(self.root / path, text)

    def config(self, **values):
        support.set_config(self.root, **values)

    def section(self, name="threshold", text="Порог скидки."):
        self.write("docs/pricing.md", '# Цены\n\n## Порог скидки <a id="%s"></a>\n\n%s\n' % (name, text))

    def work(self, kind, number, status, body="", title=None, outcome=""):
        target = "%s-%03d" % (kind.upper(), number)
        directory = support.TYPE_DIRS[kind.lower()] + ("" if kind == "adr" else "/2026")
        path = "workflow/%s/%s-item.md" % (directory, target.lower())
        header = ["# " + (title or target), "", "- Created: 2026-10-03",
                  "- Updated: 2026-10-03"]
        if kind != "aud":
            header.append("- Status: " + status)
            if status in ("completed", "canceled", "closed", "superseded", "rejected"):
                header.append("- Closed: 2026-10-03")
        if outcome:
            header.append("- Result: " + outcome)
        self.write(path, "\n".join(header) + "\n\n" + body + "\n")
        return path

    def mark(self, path, target=TARGET, symbol="def discount():", line=1, extra=()):
        self.write(path, "\n" * (line - 1) + "\n".join(
            ["# %s %s" % (support.TAG, value) for value in (target, *extra)]) +
            "\n\n" + symbol + "\n    return 0\n")

    def run_slice(self, target=TARGET, *args, expected=0):
        code, out = support.cli(self.root, "slice", target, "--format", "json", *args)
        self.assertEqual(code, expected, out)
        try:
            return json.loads(out)
        except ValueError:
            self.fail("slice must return JSON: " + out)

    def block(self, result, kind):
        return next((block for block in result["blocks"] if block["kind"] == kind),
                    {"kind": kind, "items": [], "omitted": 0, "hint": []})

    def items(self, result, kind):
        return self.block(result, kind)["items"]

    def content_size(self, result, full=False):
        return sum((0 if full else sum(item["lines"] for item in b["items"]))
                   if b["kind"] == "excerpt" else len(b["items"])
                   for b in result["blocks"])

    def test_target_forms_empty_notes_and_schema(self):
        self.section()
        self.write("src/plain.py", "pass\n")
        for kind in ("adr", "iss", "pln", "dsc", "aud"):
            self.work(kind, 18, {"adr": "accepted", "iss": "open", "pln": "new",
                                 "dsc": "open", "aud": "completed"}[kind])
        for query, kind, note in ((TARGET, "section", "no-marks"),
                                  ("docs/pricing.md", "page", "no-marks"),
                                  ("src/plain.py", "code", "file-no-marks"),
                                  ("adr-18", "decision", "no-code"),
                                  ("ISS-018", "work", "work-empty"),
                                  ("PLN-018", "work", "work-empty"),
                                  ("DSC-018", "work", "work-empty"),
                                  ("AUD-018", "work", "work-empty")):
            with self.subTest(query=query):
                result = self.run_slice(query)
                self.assertEqual(result["schema"], 1)
                self.assertEqual(result["target"]["kind"], kind)
                self.assertIn(note, [n["code"] for n in result["notes"]])
                self.assertIn("no-git", [n["code"] for n in result["notes"]])
                self.assertEqual(result["checks"]["staleness"],
                                 {"state": "no-git", "checked": 0, "total": 0})
                self.assertEqual(set(result["summary"]), set("errors warnings decisions rules concepts entry code layers tests open_work targets".split()))
                for block in result["blocks"]:
                    self.assertTrue({"kind", "items", "omitted", "hint"} <= block.keys())

    def test_status_of_target_is_first_and_codes_apply_without_changing_exit(self):
        self.work("adr", 19, "accepted")
        self.work("adr", 18, "superseded", outcome="[ADR-019](adr-019-item.md)")
        self.mark("src/main.py", "ADR-018")
        self.config(codes={"T3": "error"})
        result = self.run_slice("adr-18", "--only", "code")
        first = self.items(result, "signals")[0]
        self.assertEqual((first["code"], first["target"], first["level"]), ("T3", "ADR-018", "error"))
        self.assertNotIn("path", first)
        self.assertIn("ADR-019", first["message"])
        self.assertGreater(result["summary"]["errors"], 0)
        self.config(codes={"T3": "off"})
        result = self.run_slice("ADR-018")
        self.assertFalse(self.items(result, "signals"))
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 0)

    def test_all_inactive_target_statuses(self):
        for kind, states in (("adr", ("rejected", "superseded")), ("iss", ("closed",)),
                             ("pln", ("completed", "canceled")), ("dsc", ("closed",))):
            for state in states:
                with self.subTest(kind=kind, state=state):
                    self.work(kind, 1, state)
                    first = self.items(self.run_slice(kind + "-1"), "signals")[0]
                    self.assertEqual(first["code"], "T3")
                    self.assertIn(state, first["message"])

    def test_own_status_is_history_while_marks_and_covers_keep_action(self):
        self.section()
        cases = (("iss", "closed", "the current work item",
                  "check whether the link is needed. Remove it if it was a temporary workaround."),
                 ("dsc", "closed", "the current work item", "check the link against the discussion outcome"),
                 ("pln", "completed", "the current plan", "check whether the link to the completed plan is still relevant"),
                 ("pln", "canceled", "the current plan", "remove the dependency on the canceled plan"),
                 ("adr", "rejected", "the active decision", "remove the dependency on the rejected decision"),
                 ("adr", "superseded", "the active decision", "check the code against the new decision"))
        self.work("adr", 19, "accepted")
        for number, (kind, status, history, action) in enumerate(cases, 1):
            with self.subTest(kind=kind, status=status):
                target = "%s-%03d" % (kind.upper(), number)
                path = self.work(kind, number, status, outcome=(
                    "[ADR-019](adr-019-item.md)" if status == "superseded" else ""))
                subject = target + " " + status + (" ADR-019" if status == "superseded" else "")
                self.mark("src/status.py", extra=(target,))
                self.write("docs/status.md", '# Status <a id="status"></a>\n\n<!-- covers: %s -->\n' % target)
                for query in (target, path):
                    own = self.items(self.run_slice(query), "signals")[0]
                    self.assertEqual(own["message"], subject + " — this is a historical slice, not a slice of " + history)
                    self.assertNotIn("path", own)
                mark = next(s for s in self.items(self.run_slice(), "signals") if s["target"] == target)
                cover = self.items(self.run_slice("docs/status.md#status"), "signals")[0]
                for signal in (mark, cover):
                    self.assertEqual(signal["message"], subject + " — " + action)
                    self.assertEqual(signal["code"], "T3")
                    self.assertIn("path", signal)

    def test_obey_links_and_comarks_but_not_other_declarations(self):
        self.section()
        self.work("adr", 2, "accepted", "[Цель](../../docs/pricing.md#threshold)")
        self.work("adr", 3, "accepted")
        self.work("adr", 4, "accepted")
        self.work("adr", 5, "rejected")
        self.write(".agents/local.md", '# Правило <a id="money"></a>\n')
        self.write(".agents/lipi/local.md", '# Встроенное <a id="money"></a>\n')
        self.mark("src/main.py", extra=("ADR-003", "ADR-005", ".agents/local.md#money", ".agents/lipi/local.md#money"))
        with (self.root / "src/main.py").open("a") as stream:
            stream.write("\n# %s ADR-004\ndef unrelated():\n    pass\n" % support.TAG)
        result = self.run_slice()
        obey = {item["target"]: item for item in self.items(result, "obey")}
        self.assertEqual(set(obey), {"ADR-002", "ADR-003", ".agents/local.md#money"})
        self.assertEqual(obey["ADR-002"]["relation"], "link")
        self.assertEqual(obey["ADR-003"]["relation"], "mark")
        self.assertEqual(obey[".agents/local.md#money"]["relation"], "mark")
        self.assertIn("ADR-005", [item["target"] for item in self.items(result, "signals")])
        obsolete = next(item for item in self.items(result, "signals") if item["target"] == "ADR-005")
        self.assertEqual((obsolete["path"], obsolete["line"]), ("src/main.py", 3))

    def test_open_work_matrix_and_work_target_does_not_expand(self):
        self.section()
        statuses = [("iss", "open", True), ("iss", "in progress", True),
                    ("iss", "closed", False), ("pln", "new", True),
                    ("pln", "in progress", True), ("pln", "pending acceptance", True),
                    ("pln", "deferred", False), ("dsc", "open", True),
                    ("adr", "proposed", True), ("adr", "accepted", False),
                    ("aud", "completed", False)]
        expected = set()
        for number, (kind, status, opened) in enumerate(statuses, 1):
            self.work(kind, number, status, "[Цель](%s/docs/pricing.md#threshold)" %
                      ("../.." if kind == "adr" else "../../.."))
            if opened:
                expected.add("%s-%03d" % (kind.upper(), number))
        self.mark("src/main.py")
        result = self.run_slice()
        self.assertEqual({s["target"] for s in self.items(result, "signals") if s["code"] is None}, expected)
        self.mark("src/issue.py", "ISS-001")
        result = self.run_slice("ISS-001")
        self.assertEqual([item["path"] for item in self.items(result, "code")], ["src/issue.py"])
        self.assertEqual([(i["target"], i["code_count"]) for i in self.items(result, "targets")], [(TARGET, 1)])
        self.assertNotIn("excerpt", [b["kind"] for b in result["blocks"]])

    def test_places_symbols_layers_entry_and_default_test_patterns(self):
        self.section()
        self.config(layers={"z/*": "domain", "a/*": "api", "checks/*": "tests"}, entry=[r"^    class Entry:"])
        self.write("docs/other.md", '# Other <a id="other"></a>\n')
        self.mark("z/main.py", symbol="def declaration():", line=4, extra=("docs/other.md#other",))
        self.mark("a/entry.py", symbol="    class Entry:")
        self.mark("a/other.py")
        names = ["test_one.py", "one_test.go", "one.test.js", "one.spec.ts", "OneTest.java"]
        for name in names:
            self.mark("z/" + name)
        self.mark("checks/anything.txt")
        self.write("a/inline.py", "VALUE = 2  # %s %s\n" % (support.TAG, TARGET))
        result = self.run_slice()
        self.assertEqual([b["kind"] for b in result["blocks"]], ["excerpt", "entry", "code", "tests"])
        self.assertEqual(result["summary"]["code"], 4)
        self.assertEqual(result["summary"]["tests"], 6)
        self.assertEqual([item["path"] for item in self.items(result, "entry")], ["a/entry.py"])
        places = self.items(result, "code")
        self.assertEqual(places[0]["path"], "z/main.py")
        self.assertEqual(places[0]["symbol"], "def declaration():")
        self.assertEqual(places[0]["line"], 4)
        inline = next(i for i in places if i["path"] == "a/inline.py")
        self.assertIn("VALUE = 2", inline["symbol"])
        self.assertEqual(inline["line"], 1)
        self.assertTrue(all("via" not in i for i in self.items(result, "tests")))
        result = self.run_slice(TARGET, "--layer", "api", "--layer", "tests")
        self.assertTrue(all(i["layer"] in ("api", "tests") for k in ("entry", "code", "tests") for i in self.items(result, k)))
        self.config(tests=["verify.*"])
        self.mark("z/verify.rb")
        result = self.run_slice()
        self.assertEqual({i["path"] for i in self.items(result, "tests")}, {"checks/anything.txt", "z/verify.rb"})

    def test_file_concepts_counts_and_common_code_does_not_create_context(self):
        self.section()
        self.write("docs/other.md", '# Другой <a id="other"></a>\n\nSecret neighbor body.\n')
        self.mark("src/hub.py", extra=("docs/other.md#other",))
        self.mark("src/second.py")
        self.mark("tests/test_discount.py")
        result = self.run_slice("src/hub.py")
        self.assertEqual([b["kind"] for b in result["blocks"]], ["concepts", "tests", "code"])
        self.assertEqual({i["target"]: i["code_count"] for i in self.items(result, "concepts")}, {TARGET: 2, "docs/other.md#other": 1})
        self.assertEqual([i["path"] for i in self.items(result, "code")], ["src/second.py"])
        result = self.run_slice()
        self.assertNotIn("docs/other.md#other", [i["target"] for i in self.items(result, "context")])
        page = self.run_slice("docs/pricing.md")
        self.assertEqual(self.items(page, "concepts")[0]["code_count"], 2)

    def test_search_stages_candidates_limit_and_numeric_order(self):
        for name in ("f", "b", "a", "e", "c", "d"):
            self.write("docs/%s.md" % name, '# Match <a id="needle-%s"></a>\n' % name)
        self.write("docs/zero.md", '# Needle heading <a id="other"></a>\n')
        result = self.run_slice("needle", expected=1)
        self.assertEqual(result["error"], "ambiguous")
        self.assertEqual([i["target"] for i in result["candidates"]], ["docs/%s.md#needle-%s" % (n, n) for n in "abcde"])
        one = self.run_slice("needle-f")
        self.assertEqual(one["target"]["target"], "docs/f.md#needle-f")
        title = self.run_slice("Needle heading")
        self.assertEqual(title["target"]["target"], "docs/zero.md#other")
        for n in (10, 2, 100):
            self.work("iss", n, "open")
        works = self.run_slice("ISS", expected=1)
        self.assertEqual([i["target"] for i in works["candidates"]], ["ISS-002", "ISS-010", "ISS-100"])
        none = self.run_slice("nothing-like-this", expected=1)
        self.assertEqual(none["error"], "not-found")
        self.assertEqual(none["candidates"], [])

    def test_context_depth_follows_explicit_links_only(self):
        self.section(text="First. [Second](b.md#second)")
        self.write("docs/b.md", '# Second <a id="second"></a>\n\n[Third](c.md#third)\n')
        self.write("docs/c.md", '# Third <a id="third"></a>\n\n[Fourth](d.md#fourth)\n')
        self.write("docs/d.md", '# Fourth <a id="fourth"></a>\n\nSECRET FOURTH BODY\n')
        self.mark("src/main.py")
        for depth in (1, 2, 3):
            result = self.run_slice(TARGET, *(('--depth', str(depth)) if depth > 1 else ()))
            context = self.items(result, "context")
            self.assertEqual(len(context), depth)
            self.assertEqual(sorted(i["depth"] for i in context), list(range(1, depth + 1)))
            self.assertNotIn("SECRET FOURTH BODY", json.dumps(result))

    def test_workflow_navigation_is_neither_context_nor_transit(self):
        self.section()
        self.mark("src/main.py")
        navigation = ("INDEX.md", "masterplan.md", "index/plans.md", "index/issues.md",
                      "index/discussions.md", "index/decisions.md", "index/audits.md", "index/done/2025.md")
        for filename in navigation:
            prefix = "../" * (filename.count('/') + 1)
            self.write("workflow/" + filename,
                       '# Navigation\n\n[Target](%sdocs/pricing.md#threshold)\n\n[Unrelated](%sdocs/unrelated.md#other)\n' %
                       (prefix, prefix))
        self.write("docs/unrelated.md", '# Unrelated <a id="other"></a>\n')
        for depth in (1, 2, 3):
            result = self.run_slice(TARGET, "--depth", str(depth)) if depth > 1 else self.run_slice()
            self.assertFalse(self.items(result, "context"))
        for filename in navigation:
            target = "workflow/" + filename
            direct = self.run_slice(target)
            self.assertEqual(direct["target"]["target"], target)
            self.assertEqual({item["target"] for item in self.items(direct, "context")},
                             {TARGET, "docs/unrelated.md#other"})

    def test_page_link_does_not_become_a_neighbor_of_every_section(self):
        self.write("RULES.md", '# Rules\n\n## Description <a id="description"></a>\n\n[T3](codes.md#t3)\n')
        self.write("codes.md", '# Codes\n\n| Code | Meaning |\n| --- | --- |\n| <a id="t3"></a> T3 | Status |\n')
        self.write("docs/page-only.md", '# Page link\n\n[Rules](../RULES.md)\n')
        self.write("docs/direct.md", '# Direct section link\n\n[Description](../RULES.md#description)\n')
        self.mark("src/main.py", "RULES.md#description")
        section = self.run_slice("RULES.md#description")
        self.assertEqual({i["target"] for i in self.items(section, "context")},
                         {"codes.md#t3", "docs/direct.md"})
        page = self.run_slice("RULES.md")
        self.assertIn("docs/page-only.md", {i["target"] for i in self.items(page, "context")})
        code = self.run_slice("codes.md#t3")
        self.assertIn("RULES.md#description", {i["target"] for i in self.items(code, "context")})
        self.assertEqual(code["target"]["title"], "T3")

    def test_duplicate_work_number_returns_distinct_path_candidates(self):
        first = self.work("iss", 1, "open", title="First copy")
        second = "workflow/issue/2026/iss-001-duplicate.md"
        self.write(second, (self.root / first).read_text().replace("First copy", "Second copy"))
        result = self.run_slice("ISS-001", expected=1)
        self.assertEqual(result["error"], "ambiguous")
        self.assertEqual([item["target"] for item in result["candidates"]], sorted([first, second]))
        self.assertEqual({item["title"] for item in result["candidates"]}, {"First copy", "Second copy"})

    def test_ambiguous_anchor_candidates_precede_title_candidates(self):
        self.write("docs/b.md", '# Beta <a id="needle-b"></a>\n')
        self.write("docs/c.md", '# Gamma <a id="needle-c"></a>\n')
        self.write("docs/a.md", '# Needle title <a id="other"></a>\n')
        result = self.run_slice("needle", expected=1)
        self.assertEqual(result["error"], "ambiguous")
        self.assertEqual([item["target"] for item in result["candidates"]],
                         ["docs/b.md#needle-b", "docs/c.md#needle-c", "docs/a.md#other"])

    def test_work_markdown_path_keeps_page_form_and_underlying_status(self):
        for kind, status, id_kind in (("iss", "closed", "work"), ("adr", "rejected", "decision")):
            with self.subTest(kind=kind):
                path = self.work(kind, 1, status)
                target = kind.upper() + "-001"
                self.mark("src/" + kind + ".py", target)
                page = self.run_slice(path)
                self.assertEqual((page["target"]["kind"], page["target"]["target"]), ("page", path))
                signal = self.items(page, "signals")[0]
                self.assertEqual((signal["code"], signal["target"]), ("T3", target))
                self.assertEqual([item["path"] for item in self.items(page, "code")], ["src/" + kind + ".py"])
                by_number = self.run_slice(target)
                self.assertEqual((by_number["target"]["kind"], by_number["target"]["target"]), (id_kind, target))

    def test_covers_status_signal_has_source_location_and_respects_section_boundary(self):
        self.work("iss", 1, "closed")
        self.work("pln", 2, "canceled")
        self.write("docs/help.md", '# Help\n\n## First <a id="first"></a>\n\n<!-- covers: ISS-001 -->\n\n## Second <a id="second"></a>\n\n<!-- covers: PLN-002 -->\n')
        section = self.run_slice("docs/help.md#first")
        signals = self.items(section, "signals")
        self.assertEqual([(item["code"], item["target"], item["path"], item["line"]) for item in signals],
                         [("T3", "ISS-001", "docs/help.md", 5)])
        self.assertFalse(self.items(section, "context"))
        page = self.run_slice("docs/help.md")
        self.assertEqual([(item["target"], item["line"]) for item in self.items(page, "signals")],
                         [("ISS-001", 5), ("PLN-002", 9)])
        self.assertFalse(self.items(page, "context"))
        self.config(codes={"T3": "off"})
        disabled = self.run_slice("docs/help.md")
        self.assertFalse(self.items(disabled, "signals"))
        self.assertEqual(disabled["summary"]["warnings"], 0)

    def test_excerpt_heading_table_paragraph_list_and_decision(self):
        self.config(slice_budget=120)
        self.write("docs/forms.md", '# Forms\n\n## Heading <a id="heading"></a>\n\nFirst paragraph.\n\n### Child\n\nChild body.\n\n## Stop\n\nDo not leak.\n\n| Key | Value |\n| --- | --- |\n| Before | Excluded intervening row |\n| <a id="row"></a> A | One |\n| B | Two |\n\n<a id="paragraph"></a> Paragraph first.\nParagraph second.\n\nOther paragraph.\n\n- <a id="item"></a> Item first.\n  Continued item.\n- Other item.\n')
        for anchor in ("heading", "row", "paragraph", "item"):
            self.mark("src/" + anchor + ".py", "docs/forms.md#" + anchor)
        values = {}
        for anchor in ("heading", "row", "paragraph", "item"):
            item = self.items(self.run_slice("docs/forms.md#" + anchor, "--full"), "excerpt")[0]
            self.assertEqual(item["lines"], len(item["text"].splitlines()))
            self.assertFalse(item["cut"])
            values[anchor] = item["text"]
        self.assertIn("### Child", values["heading"])
        self.assertIn("Child body.", values["heading"])
        self.assertNotIn("Do not leak", values["heading"])
        self.assertIn("| Key | Value |", values["row"])
        self.assertNotIn("| B | Two |", values["row"])
        self.assertNotIn("Excluded intervening row", values["row"])
        self.assertEqual(len(values["row"].splitlines()), 2)
        self.assertIn("Paragraph second.", values["paragraph"])
        self.assertNotIn("Other paragraph", values["paragraph"])
        self.assertIn("Continued item.", values["item"])
        self.assertNotIn("Other item", values["item"])
        self.work("adr", 1, "accepted", "## Контекст\n\nBefore.\n\n## Decision\n\nChosen rule.\n\n### Detail\n\nDetail body.\n\n## Последствия\n\nAfter.")
        self.mark("src/decision.py", "ADR-001")
        text = self.items(self.run_slice("ADR-001", "--full"), "excerpt")[0]["text"]
        self.assertIn("Chosen rule.", text)
        self.assertIn("Detail body.", text)
        self.assertNotIn("Before.", text)
        self.assertNotIn("After.", text)

    def test_anchor_titles_use_their_own_block_and_word_boundary(self):
        prefix = "Каждое слово описывает собственный абзац и сохраняет смысл выбранной цели"
        self.assertLess(len(prefix), 79)
        self.assertGreater(len(prefix + " дополнительное"), 79)
        long_text = prefix + " дополнительное объяснение поведения."
        self.write("docs/titles.md", '# Unrelated page title\n\n## Heading title <a id="heading"></a>\n\n'
                   '| Code | Meaning |\n| --- | --- |\n| <a id="row"></a> T3 | Status |\n\n'
                   '<a id="paragraph"></a> ' + long_text + '\n\n'
                   '- <a id="item"></a> ' + long_text + '\n- Other item.\n')
        expected = {"heading": "Heading title", "row": "T3", "paragraph": prefix + "…", "item": prefix + "…"}
        for anchor, title in expected.items():
            with self.subTest(anchor=anchor):
                result = self.run_slice("docs/titles.md#" + anchor)
                self.assertEqual(result["target"]["title"], title)
                if anchor in ("paragraph", "item"):
                    self.assertLessEqual(len(title), 80)

    def test_short_excerpt_keeps_first_list_item_and_late_headings_and_links(self):
        for marker in ("-", "1."):
            with self.subTest(marker=marker):
                self.section(text=marker + " First item.\n  First continuation.\n" +
                             "\n".join(marker + " Later item %d." % n for n in range(25)) +
                             '\n\n### Later heading\n\n[Later reference](other.md#other)\n')
                self.write("docs/other.md", '# Other <a id="other"></a>\n')
                self.mark("src/main.py")
                excerpt = self.items(self.run_slice(), "excerpt")[0]
                self.assertIn("First item.", excerpt["text"])
                self.assertIn("First continuation.", excerpt["text"])
                self.assertIn("### Later heading", excerpt["text"])
                self.assertIn("[Later reference](other.md#other)", excerpt["text"])
                self.assertNotIn("Later item", excerpt["text"])
                self.assertLessEqual(excerpt["lines"], 20)
                self.assertTrue(excerpt["cut"])

    def test_short_excerpt_ignores_headings_and_links_inside_fences(self):
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                self.section(text='First paragraph.\n\n' + fence + '\n### Fake heading\n'
                             '[Fake reference](fake.md#fake)\n' + '\n'.join('code %d' % n for n in range(25)) +
                             '\n' + fence + '\n\n### Real heading\n\n[Real reference](other.md#other)\n')
                self.write("docs/other.md", '# Other <a id="other"></a>\n')
                self.mark("src/main.py")
                excerpt = self.items(self.run_slice(), "excerpt")[0]
                self.assertIn("First paragraph.", excerpt["text"])
                self.assertIn("### Real heading", excerpt["text"])
                self.assertIn("[Real reference](other.md#other)", excerpt["text"])
                self.assertNotIn("Fake heading", excerpt["text"])
                self.assertNotIn("Fake reference", excerpt["text"])
                self.assertTrue(excerpt["cut"])

    def test_symbols_skip_comments_stop_at_next_tag_or_eof_and_keep_entry_indent(self):
        self.section()
        self.write("docs/other.md", '# Other <a id="other"></a>\n')
        self.config(entry=[r"^    def entry\("])
        prefixes = ("# comment", "// comment", "/* comment */", "* comment", "-- comment", "; comment", "<!-- comment -->")
        self.write("src/comments.py", "# %s %s\n\n" % (support.TAG, TARGET) +
                   "\n".join(prefixes) + "\n    def entry():\n        pass\n")
        self.write("src/next.py", "# %s %s\n# Just a comment.\n# %s docs/other.md#other\ndef other():\n    pass\n" %
                   (support.TAG, TARGET, support.TAG))
        self.write("src/invalid-next.py", "# %s %s\n# Just a comment.\n# %s docs/missing.md#missing\ndef unrelated():\n    pass\n" %
                   (support.TAG, TARGET, support.TAG))
        self.write("src/eof.py", "# %s %s\n# Only a comment.\n" % (support.TAG, TARGET))
        result = self.run_slice()
        entries = self.items(result, "entry")
        self.assertEqual([(i["path"], i["symbol"]) for i in entries], [("src/comments.py", "def entry():")])
        self.assertEqual({i["path"]: i["symbol"] for i in self.items(result, "code")},
                         {"src/next.py": "", "src/invalid-next.py": "", "src/eof.py": ""})

    def test_slice_is_read_only_and_does_not_run_project_checks(self):
        self.section()
        self.mark("src/main.py")
        self.write("workflow/INDEX.md", "Preserve index bytes.\n")
        self.write(".agents/lipi/baseline.json", '{"schema":1,"entries":[]}\n')
        self.config(checks=[{"name": "write sentinel", "run": [sys.executable, "-c", "open('sentinel','w').write('ran')"], "mode": "quick"}])
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.run_slice()
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_staleness_full_no_git_and_disabled_count_unique_places(self):
        self.write("docs/pricing.md", '# Prices\n\n## Threshold <a id="threshold"></a>\n\nFirst.\n\n'
                   '## Other <a id="other"></a>\n\nSecond.\n')
        self.mark("src/first.py", extra=("docs/pricing.md#other",))
        self.mark("src/second.py")
        result = self.run_slice("docs/pricing.md")
        self.assertEqual(result["checks"]["staleness"], {"state": "no-git", "checked": 0, "total": 2})
        self.assertFalse(result["incomplete"])
        self.config(codes={"A4": "off"})
        disabled = self.run_slice("docs/pricing.md")
        self.assertEqual(disabled["checks"]["staleness"], {"state": "no-git", "checked": 0, "total": 0})
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-01-01T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        disabled = self.run_slice("docs/pricing.md")
        self.assertEqual(disabled["checks"]["staleness"], {"state": "full", "checked": 0, "total": 0})
        self.config(codes={})
        full = self.run_slice("docs/pricing.md")
        self.assertEqual(full["checks"]["staleness"], {"state": "full", "checked": 2, "total": 2})
        self.assertFalse(full["incomplete"])
        self.assertIn({"code": "staleness-full", "text": "checked 2 of 2 locations for staleness"}, full["notes"])
        from tests.test_history import oracle_slice
        self.assertEqual(full, oracle_slice(self.root, "docs/pricing.md"))

    def test_staleness_uses_git_when_file_listing_fails(self):
        from unittest.mock import patch
        from lipi.checker.config import load_config
        from lipi.checker.model import Project
        from lipi.slice_query import build_slice

        self.section()
        self.mark("src/main.py")
        support.git_init(self.root)
        code, out = support.commit(self.root)
        self.assertEqual(code, 0, out)
        root = self.root.resolve()
        with patch("lipi.checker.model.list_project_files", return_value=None):
            project = Project(root, load_config(root, None))
        result, code = build_slice(project, TARGET)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["checks"]["staleness"], {"state": "full", "checked": 1, "total": 1})

    def test_nested_source_metadata_in_linked_worktree(self):
        repository = self.root / 'repo'
        self.root = repository / 'project'
        self.write('lipi.json', '{}\n')
        self.section()
        self.mark('src/main.py')
        support.w(repository / 'neighbor/lipi.json', '{}\n')
        support.w(repository / 'neighbor/docs/README.md', '# Описание\n')
        self.config(repos={'neighbor': {'path': '../neighbor', 'read': ['docs']}})
        support.git_init(repository)
        code, out = support.commit(repository)
        self.assertEqual(code, 0, out)
        code, head = support.git(repository, 'rev-parse', 'HEAD')
        self.assertEqual(code, 0, head)
        checkout = self.root.parents[1] / 'checkout'
        code, out = support.git(repository, 'worktree', 'add', '--detach', str(checkout))
        self.assertEqual(code, 0, out)
        self.assertTrue((checkout / '.git').is_file())
        self.root = checkout / 'project'
        sliced = self.run_slice()
        self.assertEqual(sliced['checks']['staleness'],
                         {'state': 'full', 'checked': 1, 'total': 1, 'scope': 'local'})
        self.assertTrue(sliced['reproducible'])
        for item in sliced['checks']['repos']:
            self.assertEqual((item['state'], item['head'], item['dirty']), ('ok', head.strip(), False))
        support.w(checkout / '.gitignore', '/project/src/temporary.py\n')
        code, out = support.cli(self.root, 'map', '--format', 'json')
        self.assertEqual(code, 0, out)
        mapped = json.loads(out)
        self.assertFalse(mapped['reproducible'])
        self.assertTrue(all(item['dirty'] for item in mapped['checks']['repos']))

    def staleness_priority_project(self):
        self.config(layers={"z/*": "domain", "b/*": "api", "src/*": "app", "a/*": "last", "tests/*": "tests"},
                    entry=[r"def entry_"])
        self.write("docs/pricing.md", '# Prices\n\n## Threshold <a id="threshold"></a>\n\nFirst.\n\n'
                   '## Other <a id="other"></a>\n\nSecond.\n')
        self.mark("z/entry.py", symbol="def entry_domain():")
        self.mark("b/entry.py", symbol="def entry_api():")
        for n in range(16):
            path = ("a" if n >= 14 else "src") + "/code_%02d.py" % n
            self.mark(path, symbol="def discount_%02d():" % n,
                      target=TARGET + ",docs/pricing.md#other" if n == 0 else TARGET)
        with (self.root / "src/code_00.py").open("a") as stream:
            stream.write("\n# %s %s\ndef second_place():\n    return 0\n" % (support.TAG, TARGET))
        for n in range(2):
            self.mark("tests/test_%02d.py" % n, symbol="def entry_test_%02d():" % n)
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-01-01T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        for path in self.root.rglob("*.py"):
            path.write_text(path.read_text().replace("return 0", "return 1"))
        code, out = support.commit(self.root, "change every implementation", date="2026-01-03T09:00:00+00:00")
        self.assertEqual(code, 0, out)

    def test_staleness_partial_prioritizes_entries_then_code_and_counts_whole_places(self):
        self.staleness_priority_project()
        result = self.run_slice("docs/pricing.md")
        expected = {"state": "partial", "checked": 17, "total": 21}
        self.assertEqual(result["checks"]["staleness"], expected)
        self.assertTrue(result["incomplete"])
        signals = [s for s in self.items(result, "signals") if s["code"] == "A4"]
        self.assertEqual({s["path"] for s in signals},
                         {"z/entry.py", "b/entry.py", "a/code_14.py", "a/code_15.py"} |
                         {"src/code_%02d.py" % n for n in range(12)})
        self.assertEqual(len(signals), 18)
        self.assertEqual(result["summary"]["warnings"], 18)
        note = next(n for n in result["notes"] if n["code"] == "staleness-partial")
        self.assertEqual(note["text"], "checked 17 of 21 locations for staleness. Run lipi audit for a full check")
        code, text = support.cli(self.root, "slice", "docs/pricing.md")
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized(note["text"],
                                        "устаревание проверено для 17 из 21 мест; полная проверка — lipi audit"), text)
        from tests.test_history import oracle_slice
        full = oracle_slice(self.root, "docs/pricing.md")
        self.assertEqual(full["checks"]["staleness"], {"state": "full", "checked": 21, "total": 21})
        full_signals = self.items(full, "signals")
        self.assertTrue(all(signal in full_signals for signal in signals))
        for args in (("--only", "signals"), ("--full",), ("--layer", "tests")):
            with self.subTest(args=args):
                filtered = self.run_slice("docs/pricing.md", *args)
                self.assertEqual(filtered["checks"]["staleness"], expected)
                self.assertEqual(self.items(filtered, "signals"), signals)
        self.config(slice_budget=1)
        tiny = self.run_slice("docs/pricing.md")
        self.assertEqual(tiny["checks"]["staleness"], expected)
        self.assertEqual(tiny["summary"]["warnings"], 18)

    def test_staleness_missing_document_history_leaves_multitarget_place_unchecked(self):
        self.section()
        self.mark("src/main.py")
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-01-01T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        self.write("docs/untracked.md", '# New <a id="new"></a>\n')
        self.mark("src/main.py", extra=("docs/untracked.md#new",))
        result = self.run_slice("src/main.py")
        self.assertEqual(result["checks"]["staleness"], {"state": "partial", "checked": 0, "total": 1})
        self.assertTrue(result["incomplete"])
        self.assertIn("staleness-partial", [n["code"] for n in result["notes"]])

    def test_staleness_coarse_counts_later_documented_places_beyond_cheap_limit(self):
        self.write("docs/pricing.md", '# Prices\n\n## Threshold <a id="threshold"></a>\n\nOld rule.\n\n'
                   '## Other <a id="other"></a>\n\nNew rule.\n')
        for n in range(70):
            self.mark("src/changed_%02d.py" % n)
        self.mark("zzz/mixed.py")
        with (self.root / "zzz/mixed.py").open("a") as stream:
            stream.write("\n# %s docs/pricing.md#other\ndef other():\n    return 0\n" % support.TAG)
        self.mark("zzz/old.py")
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-01-01T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        for path in self.root.rglob("*.py"):
            if path.name != "old.py":
                path.write_text(path.read_text().replace("return 0", "return 2"))
        code, out = support.commit(self.root, "change code", date="2026-01-02T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        path = self.root / "docs/pricing.md"
        path.write_text(path.read_text().replace("New rule.", "New rule, checked after the code change."))
        code, out = support.commit(self.root, "refresh only other section", date="2026-01-04T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        result = self.run_slice("docs/pricing.md")
        self.assertEqual(result["checks"]["staleness"], {"state": "partial", "checked": 18, "total": 73})
        signals = [s for s in self.items(result, "signals") if s["code"] == "A4"]
        self.assertEqual({s["path"] for s in signals}, {"src/changed_%02d.py" % n for n in range(16)})
        self.assertEqual(result["summary"]["warnings"], 16)

    def test_audit_keeps_all_staleness_findings_beyond_slice_limit(self):
        self.staleness_priority_project()
        code, result = support.check_json(self.root, "--audit")
        self.assertIsNotNone(result)
        findings = result["errors"] + result["warnings"]
        stale = [item for item in findings if item["code"] == "A4"]
        self.assertEqual(len(stale), 22, (code, result))

    def test_budget_reserves_half_then_three_per_block_and_preserves_summary(self):
        self.section(text="\n".join("Paragraph line %d." % n for n in range(12)))
        closed = []
        for n in range(40):
            self.work("iss", n + 1, "closed")
            closed.append("ISS-%03d" % (n + 1))
        for n in range(8):
            self.work("pln", n + 1, "new", "[Цель](../../../docs/pricing.md#threshold)")
            self.mark("src/code_%02d.py" % n, extra=closed if n == 0 else ())
        for n in range(5):
            self.mark("tests/test_%02d.py" % n)
        self.config(slice_budget=24, codes={"T3": "error"})
        result = self.run_slice()
        signals = self.items(result, "signals")
        self.assertEqual([s["level"] for s in signals], ["error"] * 12 + ["info"] * 3)
        self.assertEqual(self.block(result, "signals")["omitted"], 33)
        self.assertEqual(len(self.items(result, "code")), 3)
        self.assertEqual(len(self.items(result, "tests")), 3)
        self.assertEqual(self.items(result, "excerpt")[0]["lines"], 3)
        self.assertEqual(self.content_size(result), 24)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["summary"]["errors"], 40)
        self.assertEqual(result["summary"]["open_work"], 8)
        self.assertEqual(result["summary"]["code"], 8)
        self.assertEqual(result["summary"]["tests"], 5)
        only = self.run_slice(TARGET, "--only", "signals")
        self.assertEqual([b["kind"] for b in only["blocks"]], ["signals"])
        self.assertEqual(len(self.items(only, "signals")), 24)
        self.assertEqual([s["level"] for s in self.items(only, "signals")], ["error"] * 21 + ["info"] * 3)
        self.assertEqual(only["summary"], result["summary"])
        code_only = self.run_slice(TARGET, "--only", "code,tests")
        self.assertEqual([b["kind"] for b in code_only["blocks"]], ["signals", "code", "tests"])
        self.assertTrue(self.items(code_only, "signals"))
        full = self.run_slice(TARGET, "--full")
        self.assertFalse(self.items(full, "excerpt")[0]["cut"])
        self.assertGreater(self.items(full, "excerpt")[0]["lines"], 8)
        self.assertEqual(self.content_size(full, full=True), 24)
        self.assertTrue(full["incomplete"])
        self.assertEqual(len(self.items(full, "tests")), 3)

    def test_budget_remaining_order_small_budget_and_excerpt_cap(self):
        self.section(text="\n".join("Line %d." % n for n in range(30)))
        for n in range(10):
            self.mark("src/code_%02d.py" % n)
            self.mark("tests/test_%02d.py" % n)
        self.config(slice_budget=15)
        result = self.run_slice()
        self.assertEqual(self.items(result, "excerpt")[0]["lines"], 5)
        self.assertEqual(len(self.items(result, "code")), 7)
        self.assertEqual(len(self.items(result, "tests")), 3)
        self.assertEqual(self.content_size(result), 15)
        self.config(slice_budget=1)
        tiny = self.run_slice()
        self.assertEqual(self.content_size(tiny), 1)
        self.assertEqual(self.items(tiny, "excerpt")[0]["lines"], 1)
        self.assertEqual(self.block(tiny, "code")["omitted"], 10)
        self.assertEqual(self.block(tiny, "tests")["omitted"], 10)

    def test_full_hub_keeps_global_budget_and_names_hidden_concepts(self):
        targets = []
        for n in range(20):
            target = "docs/page_%02d.md#concept" % n
            targets.append(target)
            self.write(target.split("#")[0], '# Concept %d <a id="concept"></a>\n' % n)
        self.mark("src/hub.py", targets[0], extra=targets[1:])
        self.config(slice_budget=7)
        result = self.run_slice("src/hub.py", "--full")
        self.assertEqual(result["summary"]["concepts"], 20)
        self.assertEqual(len(self.items(result, "concepts")), 7)
        self.assertEqual(self.block(result, "concepts")["omitted"], 13)
        self.assertEqual(self.content_size(result, full=True), 7)
        self.assertTrue(result["incomplete"])
        code, text = support.cli(self.root, "slice", "src/hub.py", "--full")
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized('implements 13 more concepts', 'реализует ещё 13 понятий'), text)

    def test_fallback_layers_and_symbol_length(self):
        self.section()
        self.mark("z/main.txt", symbol="x" * 100)
        self.mark("a/main.txt")
        result = self.run_slice()
        places = self.items(result, "code")
        self.assertEqual([item["layer"] for item in places], ["a", "z"])
        self.assertEqual(places[1]["symbol"], "x" * 80)

    def test_text_and_json_select_identical_places_and_excerpt_lines(self):
        self.section(text="\n".join("Unique excerpt %d." % n for n in range(20)))
        for n in range(12):
            self.mark("src/unique_%02d.py" % n, symbol="def unique_%02d():" % n)
        for n in range(6):
            self.mark("tests/test_unique_%02d.py" % n)
        self.config(slice_budget=13)
        result = self.run_slice()
        code, text = support.cli(self.root, "slice", TARGET)
        self.assertEqual(code, 0, text)
        for kind in ("code", "tests"):
            selected = {i["path"] for i in self.items(result, kind)}
            paths = (self.root / ("src" if kind == "code" else "tests")).glob("*.py")
            for path in paths:
                relative = str(path.relative_to(self.root))
                self.assertEqual(relative + ":1" in text, relative in selected, text)
        excerpt = self.items(result, "excerpt")[0]
        for n in range(20):
            line = "Unique excerpt %d." % n
            self.assertEqual(line in text, line in excerpt["text"], text)
        self.assertIn("--only code", text)
        self.assertIn(support.localized('excerpt shortened', 'обрезано'), text)

    def example_project(self, language="ru"):
        self.config(layers={"src/api/*": "api", "src/app/*": "app", "src/domain/*": "domain", "tests/*": "tests"},
                    entry=[r"post_order|apply_discount"])
        if language == "en":
            pricing = ('# Pricing\n\n## Discount threshold\n\n<a id="threshold"></a>'
                       'A 5% discount applies to orders of at least $100 excluding shipping. Compare the rounded\n'
                       'total with the threshold. See [Rounding](#rounding).\n\n'
                       '## Rounding <a id="rounding"></a>\n\nRound the total to cents.\n')
            orders = '# Orders\n\n## Order total <a id="total"></a>\n\n[Threshold](pricing.md#threshold).\n'
            architecture = '# Architecture\n\n## Monetary amounts use Money <a id="money"></a>\n'
            decision = "Discounts use the total before shipping"
            issue = "The threshold ignores refunds"
            label, suffix = "Threshold", ":"
        else:
            pricing = ('# Цены\n\n## Порог скидки\n\n<a id="threshold"></a>'
                       'Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма\n'
                       'сравнивается после округления, см. [Округление](#rounding).\n\n'
                       '## Округление <a id="rounding"></a>\n\nОкругление до копеек.\n')
            orders = '# Заказы\n\n## Сумма заказа <a id="total"></a>\n\n[Порог](pricing.md#threshold).\n'
            architecture = '# Архитектура\n\n## Деньги только в Money <a id="money"></a>\n'
            decision = "Скидка считается от суммы без доставки"
            issue = "Порог не учитывает возвраты"
            label, suffix = "Порог", ""
        self.write("docs/pricing.md", pricing)
        self.write("docs/orders.md", orders)
        self.write(".agents/architecture.md", architecture)
        self.work("adr", 18, "accepted", f"## Decision\n\n[{label}](../../{TARGET}).", title=decision)
        self.work("iss", 7, "open", f"## Observation\n\n[{label}](../../../{TARGET}).", title=issue)
        self.mark("src/api/orders.py", symbol="def post_order(request)" + suffix, line=88)
        self.mark("src/app/checkout.py", symbol="def apply_discount(order)" + suffix, line=40)
        self.mark("src/app/settings.py", symbol="DISCOUNT_THRESHOLD = Money(10_000)", line=21)
        self.mark("src/domain/discount.py", symbol="class DiscountPolicy:", line=12, extra=(".agents/architecture.md#money",))
        lines = (self.root / "src/domain/discount.py").read_text().splitlines()
        lines += [""] * (56 - len(lines)) + ["# %s %s" % (support.TAG, TARGET), "def threshold_for(customer):", "    return 0"]
        self.write("src/domain/discount.py", "\n".join(lines) + "\n")
        self.mark("tests/test_checkout.py", symbol="def test_discount_applied():", line=30)
        self.mark("tests/test_discount.py", symbol="def test_threshold_boundary():", line=8)
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-10-03T18:40:00+00:00")
        self.assertEqual(code, 0, out)
        path = self.root / "src/domain/discount.py"
        self.write("src/domain/discount.py", path.read_text().replace("return 0", "return 5", 1))
        code, out = support.commit(self.root, "change policy", date="2026-11-12T09:14:00+00:00")
        self.assertEqual(code, 0, out)

    def assert_documented_section_example(self, language):
        self.example_project(language)
        description = (support.LIPI / "docs" / language / "slice-examples.md").read_text(encoding="utf-8")
        example = description.split(f"`lipi slice {TARGET}`", 1)[1]
        expected_text = re.search(r"```text\n(.*?)\n```", example, re.S).group(1)
        expected_json = json.loads(re.search(r"```json\n(.*?)\n```", example, re.S).group(1))
        result = self.run_slice()
        self.assertEqual(result, expected_json)
        with tempfile.TemporaryDirectory(prefix="lipi-example-profile-") as profile:
            code, text = support.run(
                support.PY + [str(support.CLI), "slice", TARGET],
                cwd=self.root, env=support.language_env(Path(profile), language),
            )
        self.assertEqual(code, 0, text)
        self.assertEqual(text.strip(), expected_text)
        self.config(codes={"A4": "off"})
        result = self.run_slice()
        self.assertFalse(any(s["code"] == "A4" for s in self.items(result, "signals")))
        self.assertEqual(result["summary"]["warnings"], 0)

    def test_documented_section_example_matches_real_cli_text_and_json(self):
        self.assert_documented_section_example("ru")

    def test_documented_english_section_example_matches_real_cli_text_and_json(self):
        self.assert_documented_section_example("en")

    def test_signal_severity_beats_path_order_under_tiny_budget(self):
        self.example_project()
        self.work("iss", 1, "closed")
        self.mark("zzz/obsolete.py", extra=("ISS-001",))
        self.config(codes={"T3": "error"}, slice_budget=1)
        result = self.run_slice()
        signal = self.items(result, "signals")[0]
        self.assertEqual((signal["code"], signal["level"]), ("T3", "error"))
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertGreater(result["summary"]["warnings"], 0)
        self.assertEqual(self.content_size(result), 1)

    def test_invalid_arguments_and_new_settings_return_two(self):
        self.section()
        for args in (("--depth", "0"), ("--depth", "4"), ("--only", "unknown"), ("--format", "yaml")):
            with self.subTest(args=args):
                self.assertEqual(support.cli(self.root, "slice", TARGET, *args)[0], 2)
        for key, values in (("slice_budget", (0, -1, True, 1.5, "60", None)),
                            ("layers", ([], {"src/*": 3}, {"src/*": ""})),
                            ("tests", ("test_*", [1], [""]))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.write("lipi.json", json.dumps({key: value}))
                    code, out = support.cli(self.root, "slice", TARGET)
                    self.assertEqual(code, 2, out)
                    self.assertIn("C1", out)

    def profile_project(self):
        """Forty commits: old moves, refreshed docs and twenty newer implementations."""
        self.section()
        functions = {}
        locations = {n: n for n in range(1000)}

        def write_module(module, function):
            self.write("src/module_%04d.py" % module,
                       '"""Permanent module %04d: pricing integration boundary."""\n\n' % module +
                       "# %s %s\n" % (support.TAG, TARGET) + functions[function])

        for n in range(1000):
            functions[n] = ("def discount_%04d(amount):\n" % n +
                            "    subtotal_%04d = amount * 2\n" % n +
                            "    allowance_%04d = subtotal_%04d // 10\n" % (n, n) +
                            "    remainder_%04d = subtotal_%04d - allowance_%04d\n" % (n, n, n) +
                            "    delivery_%04d = remainder_%04d // 100\n" % (n, n) +
                            "    adjusted_%04d = remainder_%04d + delivery_%04d\n" % (n, n, n) +
                            "    return adjusted_%04d + %d\n" % (n, n))
            write_module(n, n)
        for n in range(99):
            self.write("docs/page_%03d.md" % n, '# Page %d <a id="page-%d"></a>\n' % (n, n))
        for n in range(300):
            self.work("iss", n + 1, "open")
        support.git_init(self.root)
        code, out = support.commit(self.root, "initial", date="2026-10-03T18:40:00+00:00")
        self.assertEqual(code, 0, out)
        for n in range(18):
            other = 500 + n
            left, right = locations[n], locations[other]
            write_module(left, other)
            write_module(right, n)
            locations[n], locations[other] = right, left
            message = "move discount_%04d and discount_%04d between existing modules" % (n, other)
            code, out = support.commit(self.root, message, date="2026-10-04T09:%02d:00+00:00" % n)
            self.assertEqual(code, 0, out)
        self.section(text="Порог скидки. Описание актуализировано после переноса реализаций.")
        code, out = support.commit(self.root, "refresh description after old moves", date="2026-11-01T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        for n in range(20):
            functions[n] = functions[n].replace("amount * 2", "amount * 3")
            write_module(locations[n], n)
            code, out = support.commit(self.root, "change discount_%04d semantics" % n,
                                       date="2026-11-12T09:%02d:00+00:00" % n)
            self.assertEqual(code, 0, out)
        code, out = support.git(self.root, "rev-list", "--count", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertEqual(int(out), 40)
        return locations

    def profile_mass_move(self, locations):
        """Move every implementation to the next existing file, keeping file headers."""
        bodies = {}
        for function, module in locations.items():
            path = self.root / ("src/module_%04d.py" % module)
            bodies[function] = path.read_text().splitlines(keepends=True)[3:]
        moved = {function: (module + 1) % 1000 for function, module in locations.items()}
        for function, module in moved.items():
            path = self.root / ("src/module_%04d.py" % module)
            header = path.read_text().splitlines(keepends=True)[:3]
            self.write(str(path.relative_to(self.root)), "".join(header + bodies[function]))
        code, out = support.commit(self.root, "rotate all thousand implementations between existing modules",
                                   date="2026-11-13T09:00:00+00:00")
        self.assertEqual(code, 0, out)
        code, out = support.git(self.root, "rev-list", "--count", "HEAD")
        self.assertEqual(code, 0, out)
        self.assertEqual(int(out), 41)
        return moved

    def assert_profile_result(self, result, locations, scenario="normal"):
        checked = 996 if scenario == "normal" else 16
        self.assertEqual(result["checks"]["staleness"], {"state": "partial", "checked": checked, "total": 1000})
        self.assertTrue(result["incomplete"])
        self.assertIn("staleness-partial", [n["code"] for n in result["notes"]])
        stale = [s for s in self.items(result, "signals") if s["code"] == "A4"]
        changed = {"src/module_%04d.py" % locations[n] for n in range(20)}
        inspected = (set(sorted(changed)[:16]) if scenario == "normal" else
                     {"src/module_%04d.py" % n for n in range(16)})
        expected = changed & inspected
        self.assertEqual({s["path"] for s in stale}, expected)
        self.assertEqual(len(stale), len(expected))
        self.assertTrue(all(s["level"] == "warning" for s in stale))
        for function in range(20):
            path = self.root / ("src/module_%04d.py" % locations[function])
            self.assertIn("def discount_%04d(amount):" % function, path.read_text())
        self.assertEqual(result["summary"]["warnings"], len(expected))
        self.assertEqual(result["summary"]["code"], 1000)
        self.assertLessEqual(self.content_size(result), 60)

    def test_local_profile_thousand_code_hundred_docs_three_hundred_work(self):
        locations = self.profile_project()
        for scenario in ("normal", "after-move"):
            with self.subTest(scenario=scenario):
                if scenario == "after-move":
                    locations = self.profile_mass_move(locations)
                start = time.monotonic()
                code, out = support.cli(self.root, "slice", TARGET, "--format", "json")
                elapsed = time.monotonic() - start
                self.assertEqual(code, 0, out)
                result = json.loads(out)
                self.assert_profile_result(result, locations, scenario)
                self.assertLess(elapsed, 2.0, "%s CLI slice took %.3fs" % (scenario, elapsed))


if __name__ == "__main__":
    unittest.main()
