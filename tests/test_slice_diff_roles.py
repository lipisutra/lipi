"""CLI contract for trace roles in Git slices."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import support


DOC = "docs/export.md"
ROW = DOC + "#row"
SUMMARY = DOC + "#summary"
LEGACY = DOC + "#legacy"
OBSOLETE = DOC + "#obsolete"
RECORD = DOC + "#record"
REBUILD = "src/rebuild.py"
WRITER = "src/write_row.py"
READER = "src/read_row.py"
MANUAL = "src/manual.py"
TYPO = "src/typo.py"
LIVE = "src/live.py"
RETIRED = "src/retired.py"
TEST = "tests/test_export.py"


# @trace docs/ru/slice-diff.md#json,docs/ru/slice-output.md#roles
class SliceDiffRoles(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-diff-roles-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "project"
        support.w(self.root / "lipi.json", "{}\n")

    def contract(self, **sections):
        blocks = [f'## {name.title()} <a id="{name}"></a>\n\n{text}'
                  for name, text in sections.items()]
        support.w(self.root / DOC, "\n\n".join(["# Export", *blocks]) + "\n")

    def mark(self, path, *targets):
        marks = "".join(f"# {support.TAG} {target}\n" for target in targets)
        support.w(self.root / path, f"{marks}def {Path(path).stem}():\n    return 0\n")

    def baseline(self):
        support.git_init(self.root)
        code, out = support.commit(self.root, "baseline")
        self.assertEqual(code, 0, out)

    def stage(self, *paths):
        code, out = support.git(self.root, "add", "--", *paths)
        self.assertEqual(code, 0, out)

    def response(self, *args):
        code, out = support.cli(self.root, "slice", "--format", "json", *args)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    @staticmethod
    def items(result, kind):
        return [item for block in result["blocks"] if block["kind"] == kind
                for item in block["items"]]

    def assert_roles(self, result, role, matched, *, unassigned=0, unrecognized=0):
        self.assertEqual(result["summary"]["roles"], {
            "role": role, "matched": matched, "unassigned": unassigned,
            "unrecognized": unrecognized,
        })

    def test_changed_contracts_label_only_matching_links_and_count_one_declaration(self):
        support.set_config(self.root, entry=["def rebuild"])
        self.contract(row="Write the name first.", summary="Count the records.")
        self.mark(REBUILD, SUMMARY + " role=produces", ROW + " role=consumes")
        self.mark(WRITER, ROW + " role=produces")
        self.mark(TEST, ROW, SUMMARY)
        self.baseline()

        self.contract(row="Write the identifier first.", summary="Count the records.")
        row = self.response("--diff", "HEAD")
        entry, = self.items(row, "entry")
        self.assertEqual(entry["path"], REBUILD)
        self.assertEqual((entry["via"], entry["matched_targets"]), (ROW, [ROW]))
        self.assertEqual(entry["target_roles"], [{"target": ROW, "roles": ["consumes"]}])
        self.assertEqual(entry["reasons"], [
            {"target": ROW, "reason": "contract-change", "link": "retained"},
        ])

        writers = self.response("--diff", "HEAD", "--role", "produces")
        self.assertEqual(self.items(writers, "entry"), [])
        self.assertEqual([item["path"] for item in self.items(writers, "code")], [WRITER])
        self.assertEqual(self.items(writers, "tests"), self.items(row, "tests"))
        self.assert_roles(writers, "produces", 1)

        self.contract(row="Write the identifier first.", summary="Count the distinct records.")
        both = self.response("--diff", "HEAD", "--role", "produces")
        entry, = self.items(both, "entry")
        self.assertEqual((entry["path"], entry["via"], entry["matched_targets"]),
                         (REBUILD, ROW, [ROW, SUMMARY]))
        self.assertEqual(entry["target_roles"], [
            {"target": ROW, "roles": ["consumes"]},
            {"target": SUMMARY, "roles": ["produces"]},
        ])
        self.assertEqual(entry["reasons"], [
            {"target": ROW, "reason": "contract-change", "link": "retained"},
            {"target": SUMMARY, "reason": "contract-change", "link": "retained"},
        ])
        self.assertEqual((both["summary"]["entry"], both["summary"]["code"]), (1, 2))
        self.assert_roles(both, "produces", 2)
        for language, reader, writer in (("en", "consumes the result", "produces the result"),
                                         ("ru", "потребляет результат", "формирует результат")):
            env = support.language_env(self.tmp / language, language)
            code, output = support.run(support.PY + [str(support.CLI), "slice", "--diff", "HEAD",
                                                     "--role", "produces"], cwd=self.root, env=env)
            self.assertEqual(code, 0, output)
            row, = [line for line in output.splitlines() if line.strip().startswith(REBUILD + ":")]
            self.assertEqual((row.count("#row"), row.count("#summary")), (1, 1))
            self.assertIn(reader, row.split("#row", 1)[1].split("#summary", 1)[0])
            self.assertIn(writer, row.split("#summary", 1)[1])
        test, = self.items(both, "tests")
        self.assertEqual((test["path"], test["matched_targets"]), (TEST, [ROW, SUMMARY]))
        self.assertNotIn("target_roles", test)

    def test_staged_contract_diff_uses_roles_from_the_side_of_each_link(self):
        self.contract(row="Write the name first.", legacy="Use the old fields.",
                      obsolete="Save the full record.")
        self.mark(REBUILD, ROW + " role=produces", LEGACY + " role=consumes")
        self.mark(LIVE, OBSOLETE + " role=consumes")
        self.mark(RETIRED, LEGACY + " role=produces")
        self.baseline()

        self.contract(row="Write the identifier first.", record="Use the new fields.")
        self.mark(REBUILD, ROW + " role=consumes", RECORD + " role=produces")
        self.mark(LIVE, OBSOLETE + " role=produces")
        self.mark(RETIRED)
        self.stage(DOC, REBUILD, LIVE, RETIRED)

        self.mark(REBUILD, ROW + " role=produces", RECORD + " role=consumes")
        self.mark(LIVE, OBSOLETE + " role=consumes")

        result = self.response("--staged")
        items = self.items(result, "code")
        self.assertCountEqual([item["path"] for item in items], [REBUILD, LIVE, RETIRED])
        by_path = {item["path"]: item for item in items}
        rebuild, live, retired = (by_path[path] for path in (REBUILD, LIVE, RETIRED))
        self.assertEqual((rebuild["line"], rebuild["via"], rebuild["matched_targets"]),
                         (1, LEGACY, [LEGACY, RECORD, ROW]))
        self.assertNotIn("side", rebuild)
        self.assertEqual(rebuild["target_roles"], [
            {"target": LEGACY, "roles": ["consumes"]},
            {"target": RECORD, "roles": ["produces"]},
            {"target": ROW, "roles": ["consumes"]},
        ])
        self.assertCountEqual([reason for reason in rebuild["reasons"] if "link" in reason], [
            {"target": LEGACY, "reason": "target-removed", "link": "removed"},
            {"target": RECORD, "reason": "contract-change", "link": "added"},
            {"target": ROW, "reason": "contract-change", "link": "retained"},
        ])
        self.assertEqual(live["target_roles"], [{"target": OBSOLETE, "roles": ["produces"]}])
        self.assertIn({"target": OBSOLETE, "reason": "target-removed", "link": "retained"},
                      live["reasons"])
        self.assertEqual((retired["side"], retired["line"]), ("before", 1))
        self.assertEqual(retired["target_roles"], [{"target": LEGACY, "roles": ["produces"]}])
        self.assertIn({"target": LEGACY, "reason": "target-removed", "link": "removed"},
                      retired["reasons"])

        staged = self.response("--staged", "--role", "consumes")
        self.assertEqual([item["path"] for item in self.items(staged, "code")], [REBUILD])
        self.assert_roles(staged, "consumes", 1)
        working = self.response("--diff", "HEAD", "--role", "consumes")
        self.assertCountEqual([item["path"] for item in self.items(working, "code")],
                              [REBUILD, LIVE])
        self.assert_roles(working, "consumes", 2)

    def test_staged_code_only_diff_uses_index_roles_for_dirty_linked_places(self):
        support.set_config(self.root, codes={"T5": "off"})
        self.contract(row="Write the name first.", summary="Count the records.")
        self.mark(REBUILD, ROW + " role=produces")
        self.mark(READER, SUMMARY + " role=produces", ROW + " role=consumes")
        self.mark(WRITER, ROW + " role=produces")
        self.mark(MANUAL, ROW)
        self.mark(TYPO, ROW + " role=reads")
        self.mark(TEST, ROW)
        self.baseline()

        support.sub(self.root / REBUILD, "return 0", "return 1")
        self.stage(REBUILD)
        self.mark(READER, SUMMARY + " role=produces", ROW + " role=produces")

        baseline = self.response("--staged")
        result = self.response("--staged", "--role", "consumes")
        code = self.items(result, "code")
        self.assertCountEqual([item["path"] for item in code], [READER, MANUAL, TYPO])
        self.assertEqual({item["path"]: item["target_roles"] for item in code}, {
            READER: [{"target": ROW, "roles": ["consumes"]}],
            MANUAL: [{"target": ROW, "roles": []}],
            TYPO: [{"target": ROW, "roles": [], "invalid_roles": ["reads"]}],
        })
        self.assertTrue(all(item["matched_targets"] == [ROW] for item in code))
        self.assert_roles(result, "consumes", 1, unassigned=1, unrecognized=1)
        self.assertEqual(result["summary"]["code"], 3)
        self.assertEqual(result["checks"]["staleness"], baseline["checks"]["staleness"])
        self.assertEqual(self.items(result, "tests"), self.items(baseline, "tests"))
        self.assertEqual([item["path"] for item in self.items(result, "tests")], [TEST])

        env = support.language_env(self.tmp / "ru", "ru")
        exit_code, output = support.run(
            support.PY + [str(support.CLI), "slice", "--staged", "--role", "consumes"],
            cwd=self.root, env=env)
        self.assertEqual(exit_code, 0, output)
        for path, label in ((MANUAL, "без роли"), (TYPO, "роль не распознана")):
            line, = [row for row in output.splitlines() if row.strip().startswith(path + ":")]
            self.assertIn(label, line)
        self.assertNotIn(WRITER + ":", output)

        # Both the marker and declaration have disappeared from the working tree.
        support.w(self.root / READER, "replacement = True\n")
        self.mark("src/unstaged.py", ROW + " role=consumes")
        restored = self.response("--staged", "--role", "consumes")
        self.assertEqual(self.items(restored, "code"), code)
