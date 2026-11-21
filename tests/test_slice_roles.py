"""CLI contract for trace roles in section, page, and source file slices."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import support


EXPORT = "docs/export.md"
ROW = EXPORT + "#row"
FORMAT = EXPORT + "#format"
SUMMARY = "docs/report.md#summary"
REBUILD = "src/rebuild.py"
WRITE_ROW = "src/write_row.py"
NORMALIZE = "src/normalize.py"
MANUAL = "src/manual.py"
SHOW_SUMMARY = "src/show_summary.py"
TEST = "tests/test_export.py"


# @trace docs/ru/slice-output.md#roles
class SliceRoles(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-roles-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = self.tmp / "project"
        support.w(self.root / "lipi.json", "{}\n")
        support.w(self.root / EXPORT, '# Export\n\n## Row <a id="row"></a>\n\nA row.\n\n'
                  '## Format <a id="format"></a>\n\nA file format.\n')
        support.w(self.root / "docs/report.md",
                  '# Report\n\n## Summary <a id="summary"></a>\n\nA summary.\n')

    def mark(self, path, *targets, root=None):
        marks = "".join(f"# {support.TAG} {target}\n" for target in targets)
        symbol = Path(path).stem
        support.w((root or self.root) / path, f"{marks}def {symbol}():\n    return 0\n")

    def role_fixture(self):
        support.set_config(self.root, layers={"src/*": "export"}, entry=["def rebuild"])
        self.mark(REBUILD, SUMMARY + " role=produces", ROW + " role=consumes", FORMAT)
        self.mark(WRITE_ROW, ROW + " role=produces")
        self.mark(NORMALIZE, ROW + " role=produces,consumes")
        self.mark(MANUAL, ROW)
        self.mark(SHOW_SUMMARY, SUMMARY + " role=consumes")
        self.mark(TEST, ROW, SUMMARY)

    def text(self, query, *args, language="en"):
        env = support.language_env(self.tmp / language, language)
        code, out = support.run(support.PY + [str(support.CLI), "slice", query, *args],
                                cwd=self.root, env=env)
        self.assertEqual(code, 0, out)
        return out

    def response(self, query, *args):
        return json.loads(self.text(query, "--format", "json", *args))

    @staticmethod
    def items(result, kind):
        return [item for block in result["blocks"] if block["kind"] == kind
                for item in block["items"]]

    def assert_counts(self, result, role, *, matched, unassigned, unrecognized=0):
        self.assertEqual(result["summary"]["roles"], {
            "role": role, "matched": matched,
            "unassigned": unassigned, "unrecognized": unrecognized,
        })

    def assert_paths(self, result, kind, *paths):
        self.assertCountEqual([item["path"] for item in self.items(result, kind)], paths)

    def row_text(self, output, path, number=None):
        address = f"{path}:{number} " if number is not None else path + ":"
        rows = [line.strip() for line in output.splitlines() if line.strip().startswith(address)]
        self.assertEqual(len(rows), 1, output)
        return rows[0]

    def test_section_filters_rebuild_by_its_role_for_that_anchor(self):
        self.role_fixture()
        support.git_init(self.root)
        code, out = support.commit(self.root)
        self.assertEqual(code, 0, out)
        baseline = self.response(ROW)
        self.assertEqual(baseline["checks"]["staleness"], {"state": "full", "checked": 5, "total": 5})
        self.assert_paths(baseline, "entry", REBUILD)
        self.assert_paths(baseline, "code", WRITE_ROW, NORMALIZE, MANUAL)
        self.assertEqual(baseline["summary"]["roles"], {"unassigned": 1, "unrecognized": 0})
        baseline_code = {item["path"]: item for item in self.items(baseline, "code")}
        self.assertNotIn("target_roles", baseline_code[MANUAL])
        self.assertEqual(baseline_code[NORMALIZE]["target_roles"],
                         [{"target": ROW, "roles": ["consumes", "produces"]}])

        reads = self.response(ROW, "--role", "consumes")
        self.assert_paths(reads, "entry", REBUILD)
        self.assert_paths(reads, "code", NORMALIZE, MANUAL)
        entry, = self.items(reads, "entry")
        self.assertEqual(entry["layer"], "export")
        self.assertEqual(entry["target_roles"], [{"target": ROW, "roles": ["consumes"]}])
        self.assert_counts(reads, "consumes", matched=2, unassigned=1)
        output = self.text(ROW, "--role", "consumes")
        self.assertIn("3 code locations (1 layer), including 1 entry point",
                      output.splitlines()[1])
        russian = self.text(ROW, "--role", "consumes", language="ru")
        self.assertIn("3 места в коде (1 слой), в том числе 1 точка входа",
                      russian.splitlines()[1])
        self.assertIn("consumes", self.row_text(output, REBUILD))
        self.assertIn("no role", self.row_text(output, MANUAL))
        self.assertNotIn(WRITE_ROW, output)

        writes = self.response(ROW, "--role", "produces")
        self.assert_paths(writes, "entry")
        self.assert_paths(writes, "code", WRITE_ROW, NORMALIZE, MANUAL)
        self.assert_counts(writes, "produces", matched=2, unassigned=1)
        for result in (reads, writes):
            self.assert_paths(result, "tests", TEST)
            self.assertNotIn("target_roles", self.items(result, "tests")[0])
            self.assertEqual(result["summary"]["code"], 3)
            self.assertEqual(result["checks"]["staleness"], baseline["checks"]["staleness"])

        report = self.response(SUMMARY, "--role", "produces")
        entry, = self.items(report, "entry")
        self.assertEqual(entry["path"], REBUILD)
        self.assertEqual(entry["layer"], "export")
        self.assertEqual(entry["target_roles"], [{"target": SUMMARY, "roles": ["produces"]}])
        self.assert_paths(report, "code")
        self.assert_counts(report, "produces", matched=1, unassigned=0)
        self.assert_paths(self.response(SUMMARY, "--role", "consumes"), "code", SHOW_SUMMARY)

    def test_page_keeps_both_links_when_only_one_has_a_role(self):
        self.role_fixture()
        for role, matched, unassigned in (("consumes", 2, 1), ("produces", 2, 2)):
            with self.subTest(role=role):
                result = self.response(EXPORT, "--role", role)
                entry, = self.items(result, "entry")
                self.assertEqual(entry["path"], REBUILD)
                self.assertEqual(entry["target_roles"], [
                    {"target": FORMAT, "roles": []},
                    {"target": ROW, "roles": ["consumes"]},
                ])
                self.assert_counts(result, role, matched=matched, unassigned=unassigned)
                self.assert_paths(result, "tests", TEST)
                output = self.text(EXPORT, "--role", role)
                row = self.row_text(output, REBUILD)
                self.assertIn("#format", row)
                self.assertIn("#row", row)
                self.assertIn("no role", row)
                self.assertIn("consumes", row)

    def test_file_labels_its_own_concepts_and_the_roles_of_neighboring_places(self):
        self.role_fixture()
        path = self.root / REBUILD
        support.w(path, path.read_text(encoding="utf-8") +
                  f"\n# {support.TAG} {ROW}\ndef plain():\n    return 0\n")
        result = self.response(REBUILD)
        concepts = {item["target"]: item for item in self.items(result, "concepts")}
        self.assertEqual(set(concepts), {ROW, SUMMARY, FORMAT})
        plain = {"path": REBUILD, "line": 7, "symbol": "def plain():",
                 "target_roles": [{"target": ROW, "roles": []}]}
        for target, roles in ((SUMMARY, ["produces"]), (ROW, ["consumes"]), (FORMAT, [])):
            with self.subTest(target=target):
                locations = [{
                    "path": REBUILD, "line": 1, "symbol": "def rebuild():",
                    "target_roles": [{"target": target, "roles": roles}],
                }]
                if target == ROW:
                    locations.append(plain)
                self.assertEqual(concepts[target]["locations"], locations)
        manual, = [item for item in self.items(result, "code") if item["path"] == MANUAL]
        self.assertNotIn("target_roles", manual)
        output = self.text(REBUILD)
        own_rows = [line.strip() for line in output.splitlines()
                    if line.strip().startswith(f"{REBUILD}:1 ")]
        for target, role, label in ((SUMMARY, "produces", "produces the result"),
                                    (ROW, "consumes", "consumes the result"),
                                    (FORMAT, "produces", "no role")):
            with self.subTest(target=target):
                self.assertTrue(any(f"{target} ({label})" in row for row in own_rows), output)
                for args in ((), ("--role", role)):
                    entry, = self.items(self.response(target, *args), "entry")
                    self.assertEqual((entry["path"], entry["line"]), (REBUILD, 1))
        output = self.text(REBUILD, language="ru")
        self.assertIn(f"{ROW} (без роли)", self.row_text(output, REBUILD, number=7))

        concepts = self.items(self.response(MANUAL), "concepts")
        self.assertTrue(concepts)
        self.assertTrue(all("locations" not in item for item in concepts))

        result = self.response(REBUILD, "--role", "produces")
        concepts = {item["target"]: item for item in self.items(result, "concepts")}
        self.assertEqual(concepts[ROW]["locations"], [plain])

        result = self.response(REBUILD, "--role", "consumes")
        self.assert_paths(result, "code", NORMALIZE, MANUAL, SHOW_SUMMARY)
        self.assert_paths(result, "tests", TEST)
        self.assert_counts(result, "consumes", matched=2, unassigned=1)
        places = {item["path"]: item["target_roles"] for item in self.items(result, "code")}
        self.assertEqual(places, {
            NORMALIZE: [{"target": ROW, "roles": ["consumes", "produces"]}],
            MANUAL: [{"target": ROW, "roles": []}],
            SHOW_SUMMARY: [{"target": SUMMARY, "roles": ["consumes"]}],
        })

        support.set_config(self.root, slice_budget=4)
        result = self.response(REBUILD, "--only", "concepts")
        row, = [item for item in self.items(result, "concepts") if item["target"] == ROW]
        self.assertEqual([item["line"] for item in row["locations"]], [1])
        self.assertEqual(row["locations_omitted"], 1)
        self.assertNotIn("def plain", self.text(REBUILD, "--only", "concepts"))

    def test_typo_and_unassigned_are_distinct_even_when_t5_is_off(self):
        support.set_config(self.root, codes={"T5": "off"})
        self.mark(MANUAL, ROW)
        self.mark(TEST, ROW)
        for value, valid, invalid in (("reads", [], "reads"),
                                      ("consumes,produce", ["consumes"], "produce")):
            self.mark(REBUILD, ROW + " role=" + value)
            for role in (None, "consumes", "produces"):
                with self.subTest(value=value, role=role):
                    args = ("--role", role) if role else ()
                    result = self.response(ROW, *args)
                    self.assert_paths(result, "code", REBUILD, MANUAL)
                    self.assert_paths(result, "tests", TEST)
                    self.assertEqual(result["summary"]["code"], 2)
                    places = {item["path"]: item for item in self.items(result, "code")}
                    self.assertEqual(places[REBUILD]["target_roles"], [
                        {"target": ROW, "roles": valid, "invalid_roles": [invalid]},
                    ])
                    if role:
                        self.assertEqual(places[MANUAL]["target_roles"],
                                         [{"target": ROW, "roles": []}])
                        self.assert_counts(result, role, matched=int(role in valid),
                                           unassigned=1, unrecognized=1)
                    else:
                        self.assertNotIn("target_roles", places[MANUAL])
                        self.assertEqual(result["summary"]["roles"],
                                         {"unassigned": 1, "unrecognized": 1})
                    self.assertNotIn("target_roles", self.items(result, "tests")[0])
                    for language, error_label in (
                            ("en", "unrecognized role"), ("ru", "роль не распознана")):
                        output = self.text(ROW, *args, language=language)
                        bad_row = self.row_text(output, REBUILD)
                        self.assertIn(error_label, bad_row)
                        self.assertIn(invalid, bad_row)
                        self.assertNotIn(error_label, self.row_text(output, MANUAL))
                        summary = output.splitlines()[1]
                        if language == "en":
                            self.assertIn("1 location with an unrecognized role", summary)
                            self.assertIn("1 more location without a role" if role
                                          else "locations without a role (1)", summary)
                        else:
                            self.assertIn("1 место с нераспознанной ролью", summary)
                            self.assertIn("ещё 1 место без роли" if role
                                          else "мест без роли — 1", summary)

    def test_unclassified_project_adds_role_data_only_when_requested(self):
        self.mark(MANUAL, SUMMARY, ROW)
        self.mark(TEST, SUMMARY, ROW)
        for query in (ROW, EXPORT, MANUAL):
            with self.subTest(query=query):
                result = self.response(query)
                self.assertNotIn("roles", result["summary"])
                for block in result["blocks"]:
                    for item in block["items"]:
                        self.assertNotIn("target_roles", item)
                        self.assertNotIn("locations", item)
                self.assertNotIn("no role", self.text(query))

        place, = self.items(self.response(ROW), "code")
        self.assertEqual(place["line"], 2)
        result = self.response(ROW, "--role", "consumes")
        place, = self.items(result, "code")
        self.assertEqual(place["line"], 1)
        self.assertEqual(place["target_roles"], [{"target": ROW, "roles": []}])
        test, = self.items(result, "tests")
        self.assertEqual((test["path"], test["line"]), (TEST, 2))
        self.assert_counts(result, "consumes", matched=0, unassigned=1)

    def test_connected_roles_use_canonical_targets_with_layer_and_read_boundaries(self):
        core = self.tmp / "core"
        legacy_row = "./docs/%65xport.md#r%6Fw"
        support.w(core / EXPORT, (self.root / EXPORT).read_text(encoding="utf-8"))
        support.w(core / "lipi.json", json.dumps({
            "layers": {"src/*": "export"},
            "repos": {"app": {"path": "../project", "read": ["docs"]}},
        }))
        support.set_config(self.root, layers={"src/*": "export"}, repos={
            "core": {"path": "../core", "read": ["docs", "code"]},
        })
        self.mark(REBUILD, legacy_row + " role=consumes", "core::" + legacy_row + " role=produces")
        self.mark(REBUILD, "app::" + legacy_row + " role=consumes", root=core)

        local = self.response(ROW, "--role", "consumes")
        self.assertEqual([(item["repo"], item["target_roles"]) for item in self.items(local, "code")],
                         [(None, [{"target": ROW, "roles": ["consumes"]}]),
                          ("core", [{"target": ROW, "roles": ["consumes"]}])])
        self.assert_counts(local, "consumes", matched=2, unassigned=0)
        local_layer = self.response(ROW, "--role", "consumes", "--layer", "export")
        neighbor_layer = self.response(ROW, "--role", "consumes", "--layer", "core::export")
        for result, repo in ((local_layer, None), (neighbor_layer, "core")):
            self.assertEqual([item["repo"] for item in self.items(result, "code")], [repo])
            self.assert_counts(result, "consumes", matched=1, unassigned=0)
            self.assertEqual(result["checks"]["staleness"], local["checks"]["staleness"])
        output = self.text(ROW, "--role", "consumes", "--layer", "core::export")
        self.assertIn("consumes", self.row_text(output, "core::" + REBUILD))
        self.assertNotIn(legacy_row, output)

        external_id = "core::" + ROW
        external = self.response(external_id, "--role", "produces")
        place, = self.items(external, "code")
        self.assertIsNone(place["repo"])
        self.assertEqual(place["target_roles"], [{"target": external_id, "roles": ["produces"]}])
        self.assert_counts(external, "produces", matched=1, unassigned=0)

        support.set_config(self.root, repos={"core": {"path": "../core", "read": ["docs"]}})
        docs_only = self.response(ROW, "--role", "consumes")
        self.assertEqual([item["repo"] for item in self.items(docs_only, "code")], [None])
        self.assert_counts(docs_only, "consumes", matched=1, unassigned=0)

        core.rename(self.tmp / "unavailable")
        result = self.response(ROW, "--role", "consumes")
        self.assertEqual([item["repo"] for item in self.items(result, "code")], [None])
        self.assert_counts(result, "consumes", matched=1, unassigned=0)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["checks"]["repos"][1]["state"], "unavailable")

        offline = self.response(external_id, "--role", "produces")
        self.assertTrue(offline["incomplete"])
        self.assert_paths(offline, "code")
        self.assert_counts(offline, "produces", matched=0, unassigned=0)
