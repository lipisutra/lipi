"""CLI acceptance of slices rooted in changes to marked contracts."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import support


DOC = "docs/export.md"
ROW = DOC + "#row"
RECORD = DOC + "#record"
WRITER = "src/export.py"
READER_TEST = "tests/test_export.py"
INTRO = "Export format for downloads."
BEFORE = '## Row <a id="row"></a>\n\nWrite the name before the identifier.'
AFTER = '## Row <a id="row"></a>\n\nWrite the identifier before the name.'


# @trace docs/ru/slice-diff.md#response,docs/ru/slice-diff.md#json
class SliceChangedContracts(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-contracts-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.write("lipi.json", "{}\n")
        self.contract(BEFORE)

    def write(self, path, text):
        support.w(self.root / path, text)

    def contract(self, section, intro=INTRO):
        self.write(DOC, f"# Export\n\n{intro}\n\n{section}\n")

    def mark(self, path, symbol, *targets, root=None):
        marks = f"# {support.TAG} {', '.join(targets)}\n" if targets else ""
        support.w((root or self.root) / path, f"{marks}def {symbol}():\n    return 0\n")

    def baseline(self, root=None):
        root = root or self.root
        support.git_init(root)
        code, out = support.commit(root, "baseline")
        self.assertEqual(code, 0, out)

    def stage(self, *paths):
        code, out = support.git(self.root, "add", "--", *paths)
        self.assertEqual(code, 0, out)

    def run_slice(self, *args):
        code, out = support.run(support.PY + [str(support.CLI), "slice", "--format", "json", *args],
                                cwd=self.root)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def output(self, language, *args):
        env = support.language_env(Path(self.tmp.name) / language, language)
        code, out = support.run(support.PY + [str(support.CLI), "slice", *args],
                                cwd=self.root, env=env)
        self.assertEqual(code, 0, out)
        return out

    @staticmethod
    def items(result, kind):
        return [item for block in result["blocks"] if block["kind"] == kind
                for item in block["items"]]

    def test_wording_only_change_shows_both_versions_and_linked_places(self):
        support.set_config(self.root, entry=["write_row"])
        self.mark(WRITER, "write_row", ROW)
        self.mark(READER_TEST, "test_read_row", ROW)
        self.baseline()
        self.contract(AFTER)
        for args in (("--diff", "HEAD"), ("--staged",)):
            with self.subTest(args=args):
                if args == ("--staged",):
                    self.stage(DOC)
                result = self.run_slice(*args)
                diff = result["checks"]["diff"]
                self.assertIs(type(diff["unanchored"]), int)
                self.assertEqual((diff["files"], diff["unmarked"], diff["unanchored"]), (0, 0, 0))
                self.assertEqual(diff["sections"], [{"target": ROW, "before": BEFORE, "after": AFTER}])
                reason = {"target": ROW, "reason": "contract-change", "link": "retained"}
                entry, = self.items(result, "entry")
                test, = self.items(result, "tests")
                self.assertEqual((entry["path"], entry["via"], entry["matched_targets"], entry["reasons"]),
                                 (WRITER, ROW, [ROW], [reason]))
                self.assertEqual((test["path"], test["matched_targets"], test["reasons"]),
                                 (READER_TEST, [ROW], [reason]))
                self.assertNotIn("via", test)

        self.contract(AFTER, intro="Export format for downloads and reports.")
        diff = self.run_slice("--diff", "HEAD")["checks"]["diff"]
        self.assertEqual(diff["unanchored"], 1)
        self.assertEqual(diff["unmarked"], 0)
        self.assertEqual(diff["sections"], [{"target": ROW, "before": BEFORE, "after": AFTER}])
        self.assertEqual(self.run_slice("--staged")["checks"]["diff"]["unanchored"], 0)

    def test_renamed_anchor_shows_corrected_function_and_forgotten_test(self):
        self.write("docs/README.md", "# Documentation\n\n- [Export](export.md)\n")
        self.mark(WRITER, "write_row", ROW)
        self.mark(READER_TEST, "test_read_row", ROW)
        self.baseline()
        new_section = AFTER.replace('id="row"', 'id="record"')
        self.contract(new_section)
        self.mark(WRITER, "write_row", RECORD)
        for args in (("--diff", "HEAD"), ("--staged",)):
            with self.subTest(args=args):
                if args == ("--staged",):
                    self.stage(DOC, WRITER)
                result = self.run_slice(*args)
                self.assertCountEqual(result["checks"]["diff"]["sections"], [
                    {"target": ROW, "before": BEFORE, "after": None},
                    {"target": RECORD, "before": None, "after": new_section},
                ])
                writer, = self.items(result, "code")
                self.assertEqual((writer["path"], writer["via"], writer["matched_targets"]),
                                 (WRITER, RECORD, [RECORD, ROW]))
                self.assertNotIn("side", writer)
                self.assertCountEqual([reason for reason in writer["reasons"]
                                       if reason["reason"] != "code-change"], [
                    {"target": ROW, "reason": "target-removed", "link": "removed"},
                    {"target": RECORD, "reason": "contract-change", "link": "added"},
                ])
                test, = self.items(result, "tests")
                self.assertEqual((test["path"], test["matched_targets"]), (READER_TEST, [ROW]))
                self.assertEqual(test["reasons"], [
                    {"target": ROW, "reason": "target-removed", "link": "retained"},
                ])

                for language, labels in (
                    ("en", ("link added", "link removed", "deleted target")),
                    ("ru", ("ссылка добавлена", "ссылка убрана", "удалённую цель")),
                ):
                    text = self.output(language, *args)
                    for section in result["checks"]["diff"]["sections"]:
                        self.assertIn(section["target"], text)
                        wording = section["after"] or section["before"]
                        self.assertIn(wording.splitlines()[-1], text)
                    writer_line, = [line for line in text.splitlines() if WRITER + ":" in line]
                    test_line, = [line for line in text.splitlines() if READER_TEST + ":" in line]
                    self.assertIn("#record", writer_line)
                    self.assertIn("#row", writer_line)
                    self.assertIn(labels[0], writer_line)
                    self.assertIn(labels[1], writer_line)
                    self.assertIn("#row", test_line)
                    self.assertIn(labels[2], test_line)

        code, out = support.cli(self.root, "check", "--format", "json")
        self.assertEqual(code, 1, out)
        findings = json.loads(out)
        self.assertEqual([(item["code"], item["file"], item["subject"])
                          for item in findings["errors"] + findings["warnings"]], [("T1", READER_TEST, ROW)])

    def test_long_wording_has_the_same_excerpt_in_text_and_json(self):
        support.set_config(self.root, slice_budget=6)
        head = '## Row <a id="row"></a>'
        lines = [head] + ["Field %d stays the same." % n for n in range(1, 12)]
        lines[8] = "Write the original price."
        self.contract("\n".join(lines))
        self.baseline()
        lines[8] = "Write the discounted price."
        self.contract("\n".join(lines))

        short = self.run_slice("--diff", "HEAD")
        section, = short["checks"]["diff"]["sections"]
        self.assertEqual(section["before"], "Write the original price.")
        self.assertEqual(section["after"], "Write the discounted price.")
        self.assertEqual(section["omitted"], {"before": 11, "after": 11})
        self.assertTrue(short["incomplete"])
        full_section, = self.run_slice("--diff", "HEAD", "--full")["checks"]["diff"]["sections"]
        self.assertEqual(full_section["after"].splitlines(), lines)
        for language in ("en", "ru"):
            short_text = self.output(language, "--diff", "HEAD")
            self.assertIn(section["before"], short_text)
            self.assertIn(section["after"], short_text)
            self.assertIn("--full", short_text)
            self.assertNotIn(lines[-1], short_text)
            full_text = self.output(language, "--diff", "HEAD", "--full")
            for line in full_section["before"].splitlines() + full_section["after"].splitlines():
                self.assertIn(line, full_text)
            self.assertNotIn("--full", full_text)

    def test_unanchored_edit_and_section_without_links_are_distinct(self):
        self.baseline()
        self.contract(AFTER, intro="A new introduction.")
        response = self.run_slice("--diff", "HEAD")
        diff = response["checks"]["diff"]
        self.assertEqual(diff["unanchored"], 1)
        self.assertTrue(any(note["code"] == "diff-unanchored" for note in response["notes"]))
        self.assertIs(diff["sections"][0]["linked"], False)
        for language, messages in (
            ("en", ("outside anchor regions", "linked locations")),
            ("ru", ("вне областей якорей", "связанных мест")),
        ):
            text = self.output(language, "--diff", "HEAD").lower()
            for message in messages:
                self.assertIn(message, text)

        self.mark(READER_TEST, "test_read_row", ROW)
        self.stage(READER_TEST)
        filtered = self.run_slice("--diff", "HEAD", "--only", "excerpt")
        self.assertFalse(self.items(filtered, "tests"))
        self.assertNotEqual(filtered["checks"]["diff"]["sections"][0].get("linked"), False)

    def test_staged_mixed_diff_keeps_index_titles_and_code_links(self):
        checksum = "docs/checksum.md#hash"
        provider = "src/checksum.py"
        consumer = "src/read_checksum.py"
        tracked = "src/tracked.py"
        self.write("docs/checksum.md", '# Checksum\n\n## Hash <a id="hash"></a>\n\nKeep the original hash.\n')
        self.mark(WRITER, "write_row", ROW)
        self.mark(provider, "checksum", checksum)
        self.mark(consumer, "read_checksum", checksum)
        self.mark(tracked, "pending")
        self.baseline()

        self.contract('## Record <a id="record"></a>\n\nWrite the identifier first.')
        self.mark(WRITER, "write_row", RECORD)
        support.sub(self.root / provider, "return 0", "return 1")
        self.stage(DOC, WRITER, provider)
        indexed = self.run_slice("--staged")

        self.contract('## Worktree record <a id="record"></a>\n\nDraft wording.\n\n'
                      '## Worktree row <a id="row"></a>\n\nReturn to the previous format.')
        self.mark(tracked, "pending", checksum)
        self.mark("src/untracked.py", "untracked", checksum)
        self.mark(consumer, "read_checksum")
        result = self.run_slice("--staged")

        self.assertCountEqual([(item["path"], item["matched_targets"]) for item in self.items(result, "code")],
                              [(WRITER, [RECORD, ROW]), (consumer, [checksum])])
        titles = {item["target"]: item["title"] for item in self.items(result, "concepts")}
        self.assertEqual(titles[RECORD], "Record")
        self.assertEqual(titles, {item["target"]: item["title"] for item in self.items(indexed, "concepts")})
        self.assertEqual(result["checks"]["diff"]["unmarked"], indexed["checks"]["diff"]["unmarked"])

    def test_removed_anchor_distinguishes_remaining_and_removed_markers(self):
        self.mark(WRITER, "write_row", ROW)
        self.mark(READER_TEST, "test_read_row", ROW)
        self.baseline()
        self.contract(BEFORE.replace(' <a id="row"></a>', ""))
        writer, = self.items(self.run_slice("--diff", "HEAD"), "code")
        self.assertEqual((writer["path"], writer["reasons"]), (WRITER, [
            {"target": ROW, "reason": "target-removed", "link": "retained"},
        ]))

        self.mark(WRITER, "write_row")
        result = self.run_slice("--diff", "HEAD")
        self.assertEqual(result["checks"]["diff"]["sections"], [
            {"target": ROW, "before": BEFORE, "after": None},
        ])
        writer, = self.items(result, "code")
        test, = self.items(result, "tests")
        self.assertEqual((writer["path"], writer["side"], writer["line"], writer["symbol"]),
                         (WRITER, "before", 1, "def write_row():"))
        self.assertEqual([reason for reason in writer["reasons"] if reason["reason"] != "code-change"], [
            {"target": ROW, "reason": "target-removed", "link": "removed"},
        ])
        self.assertEqual((test["path"], test["reasons"]), (READER_TEST, [
            {"target": ROW, "reason": "target-removed", "link": "retained"},
        ]))

    def test_adr_number_and_anchor_give_one_location_with_both_reasons(self):
        path = "workflow/adr/adr-007-export.md"
        target = path + "#fields"
        self.write(path, '# Export format\n\n- Status: accepted\n\n## Decision <a id="fields"></a>\n\n'
                   'Write the name before the identifier.\n')
        self.mark(WRITER, "write_row", "adr-7", target)
        self.mark("src/provider.py", "provide_row", target)
        self.baseline()
        support.sub(self.root / path, "the name before the identifier", "the identifier before the name")
        support.sub(self.root / "src/provider.py", "return 0", "return 1")

        result = self.run_slice("--diff", "HEAD")
        writers = [item for item in self.items(result, "code") if item["path"] == WRITER]
        writer, = writers
        self.assertEqual(writer["matched_targets"], ["ADR-007", target])
        self.assertEqual(writer["via"], "ADR-007")
        self.assertCountEqual([reason for reason in writer["reasons"] if reason["reason"] != "code-change"], [
            {"target": "ADR-007", "reason": "decision-number", "link": "retained"},
            {"target": target, "reason": "contract-change", "link": "retained"},
        ])
        self.assertEqual([reason["target"] for reason in writer["reasons"]
                          if reason["reason"] == "code-change"], [target])

    def test_neighbor_places_follow_read_scopes_and_contract_owner(self):
        neighbor = self.root.parent / "neighbor"
        support.w(neighbor / "lipi.json", json.dumps({"repos": {
            "owner": {"path": "../project", "read": ["docs"]},
        }}))
        support.w(neighbor / DOC, f"# Neighbor export\n\n{BEFORE}\n")
        self.mark(WRITER, "write_row", "owner::" + ROW, root=neighbor)
        self.mark(READER_TEST, "test_read_row", "owner::" + ROW, root=neighbor)
        self.mark("src/local_export.py", "write_local_row", ROW, root=neighbor)
        self.baseline(neighbor)
        support.set_config(self.root, repos={"neighbor": {"path": "../neighbor", "read": ["code"]}})
        self.baseline()
        self.contract(AFTER)

        visible_code = self.run_slice("--diff", "HEAD")
        writer, = self.items(visible_code, "code")
        reason = {"target": ROW, "reason": "contract-change", "link": "retained"}
        self.assertEqual((writer["repo"], writer["path"], writer["reasons"]), ("neighbor", WRITER, [reason]))
        self.assertFalse(self.items(visible_code, "tests"))
        self.assertEqual(visible_code["checks"]["repos"][1]["read"], ["code"])

        support.set_config(self.root, repos={"neighbor": {"path": "../neighbor", "read": ["code", "tests"]}})
        visible_tests = self.run_slice("--diff", "HEAD")
        test, = self.items(visible_tests, "tests")
        self.assertEqual((test["repo"], test["path"], test["reasons"]), ("neighbor", READER_TEST, [reason]))
        source = visible_tests["checks"]["repos"][1]
        self.assertEqual((source["repo"], source["state"], source["read"]), ("neighbor", "ok", ["code", "tests"]))
        staleness = visible_tests["checks"]["staleness"]
        self.assertEqual((staleness["scope"], staleness["total"]), ("local", 0))
        self.assertFalse(any(item["code"] == "A4" for item in self.items(visible_tests, "signals")))

        self.contract(AFTER.replace(' <a id="row"></a>', ""))
        deleted = self.run_slice("--diff", "HEAD")
        reader, = self.items(deleted, "tests")
        self.assertEqual((reader["repo"], reader["reasons"]), ("neighbor", [
            {"target": ROW, "reason": "target-removed", "link": "retained"},
        ]))
        self.contract(AFTER)

        neighbor.rename(self.root.parent / "relocated")
        unavailable = self.run_slice("--diff", "HEAD")
        self.assertTrue(unavailable["incomplete"])
        self.assertFalse(self.items(unavailable, "code"))
        self.assertFalse(self.items(unavailable, "tests"))
        source = unavailable["checks"]["repos"][1]
        self.assertEqual((source["repo"], source["state"]), ("neighbor", "unavailable"))
        self.assertEqual(unavailable["checks"]["diff"]["sections"], [
            {"target": ROW, "before": BEFORE, "after": AFTER, "linked": False},
        ])

if __name__ == "__main__":
    unittest.main()
