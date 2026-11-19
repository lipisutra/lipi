"""Map counts explicit code/test places across project targets."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support


# @trace docs/ru/map.md#rows,docs/ru/map.md#counts,docs/ru/map.md#output,docs/ru/map.md#exit
class MapContract(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lipi-map-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("lipi.json", "{}\n")

    def write(self, path, text):
        support.w(self.root / path, text)

    def config(self, **values):
        support.set_config(self.root, **values)

    def page(self, path, *anchors):
        self.write(path, "# " + path + "\n\n" + "\n".join(
            '## %s <a id="%s"></a>\n\nText.\n' % (anchor, anchor)
            for anchor in anchors))

    def mark(self, path, *targets):
        self.write(path, "".join("# %s %s\n" % (support.TAG, target)
                                 for target in targets) + "value = 1\n")

    def work(self, path, status="accepted", header="", *anchors):
        self.write(path, "# Decision\n\n- Status: " + status + "\n" + header +
                   "\n" + "\n".join('## %s <a id="%s"></a>\n' % (a, a)
                                      for a in anchors))

    def run_map(self):
        code, out = support.cli(self.root, "map", "--format", "json")
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def rows(self, result):
        return {row["target"]: row for row in result["rows"]}

    def test_empty_project_and_unmarked_pages_return_zero(self):
        result = self.run_map()
        self.assertEqual(result["schema"], 1)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["layers"], [])
        self.assertIsInstance(result["note"], str)
        self.assertFalse((self.root / ".git").exists())
        code, text = support.cli(self.root, "map")
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized('no matching targets', 'подходящих целей нет'), text.lower())
        self.assertEqual(result["note"], "0 means no links were found. An implementation may still exist.")
        self.assertIn(support.localized(result["note"],
                                        "0 означает: связей не найдено, а не отсутствие реализации."), text)
        self.page("docs/feature.md", "one", "two")
        result = self.run_map()
        self.assertEqual(list(self.rows(result)), ["docs/feature.md"])
        self.assertEqual(result["rows"][0]["code"], {})
        self.assertEqual(result["rows"][0]["tests"], 0)
        code, text = support.cli(self.root, "map")
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized('no trace markers', 'меток нет'), text)
        self.assertEqual(result["note"], "0 means no links were found. An implementation may still exist.")
        self.assertIn(support.localized(result["note"],
                                        "0 означает: связей не найдено, а не отсутствие реализации."), text)

    def test_real_marks_expand_all_anchors_but_links_and_covers_do_not(self):
        self.page("docs/feature.md", "used", "zero")
        self.page("docs/tests.md", "used", "zero")
        self.page("docs/unmarked.md", "one", "two")
        self.page("docs/declared.md", "one", "two")
        self.write("docs/navigation.md", "# Navigation\n\n"
                   "[Section](unmarked.md#one)\n[Page](unmarked.md)\n\n"
                   "<!-- covers: docs/declared.md#one -->\n")
        self.mark("src/main.py", "docs/feature.md#used")
        self.mark("tests/test_feature.py", "docs/tests.md#used")
        result = self.run_map()
        rows = self.rows(result)
        self.assertEqual(set(rows), {"docs/feature.md#used", "docs/feature.md#zero",
                                    "docs/tests.md#used", "docs/tests.md#zero",
                                    "docs/unmarked.md", "docs/declared.md",
                                    "docs/navigation.md"})
        self.assertEqual(rows["docs/feature.md#used"]["code"], {"src": 1})
        self.assertEqual(rows["docs/tests.md#used"]["tests"], 1)
        for target, row in rows.items():
            if target != "docs/feature.md#used":
                self.assertEqual(row["code"], {"src": 0}, target)
            if target != "docs/tests.md#used":
                self.assertEqual(row["tests"], 0, target)
        self.assertEqual(rows["docs/feature.md#zero"]["kind"], "section")
        self.assertEqual(rows["docs/unmarked.md"]["kind"], "page")

        code, text = support.cli(self.root, "map", "--format", "text")
        self.assertEqual(code, 0, text)
        cells = [[cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
                 for line in text.splitlines() if "|" in line]
        for target, row in rows.items():
            rendered = next(line for line in cells if line[0] == target)
            self.assertEqual([int(value) for value in rendered[-2:]],
                             [row["code"]["src"], row["tests"]], rendered)
        self.assertEqual(result["note"], "0 means no links were found. An implementation may still exist.")
        self.assertIn(support.localized(result["note"],
                                        "0 означает: связей не найдено, а не отсутствие реализации."), text)

    def test_decision_aliases_count_once_and_refinements_do_not_inherit_marks(self):
        self.config(decisions="decisions")
        self.work("decisions/0001-base.md", "accepted", "", "base", "unused")
        self.work("decisions/0002-child.md", "accepted",
                  "- Refines: [Base](0001-base.md)\n", "child", "unused")
        self.work("decisions/0010-last.md", "rejected", "", "last", "unused")
        self.mark("src/main.py", "ADR-2,adr-0002,ADR-002",
                  "ADR-0002", "decisions/0002-child.md#child")
        with (self.root / "src/main.py").open("a") as stream:
            stream.write("\n# %s ADR-2\nother = 2\n" % support.TAG)
        self.mark("tests/test_last.py", "decisions/0010-last.md#last")
        result = self.run_map()
        rows = self.rows(result)
        self.assertEqual(list(rows), ["ADR-001", "ADR-002",
                                     "decisions/0002-child.md#child",
                                     "decisions/0002-child.md#unused", "ADR-010",
                                     "decisions/0010-last.md#last",
                                     "decisions/0010-last.md#unused"])
        self.assertEqual(rows["ADR-001"]["code"], {"src": 0})
        self.assertEqual(rows["ADR-002"]["code"], {"src": 2})
        self.assertEqual(rows["decisions/0002-child.md#child"]["code"], {"src": 1})
        self.assertEqual(rows["ADR-010"]["tests"], 0)
        self.assertEqual(rows["decisions/0010-last.md#last"]["tests"], 1)
        self.assertEqual(rows["ADR-010"]["status"], "rejected")
        self.assertEqual(rows["decisions/0010-last.md#unused"]["status"], "rejected")

    def test_layers_adjacent_groups_and_default_or_replaced_test_patterns(self):
        first, second = "docs/feature.md#one", "docs/feature.md#two"
        self.page("docs/feature.md", "one", "two")
        self.config(layers={"z/*": "domain", "z/overlap/*": "unused",
                            "api/*": "api", "checks/*": "tests", "empty/*": "empty"})
        self.mark("z/overlap/main.py", first + "," + second, first)
        with (self.root / "z/overlap/main.py").open("a") as stream:
            stream.write("\n# %s %s\nother = 2\n" % (support.TAG, first))
        for path in ("api/main.py", "main.py", "b/main.py"):
            self.mark(path, first)
        for name in ("test_one.py", "one_test.go", "one.test.js", "one.spec.ts", "OneTest.java"):
            self.mark("z/" + name, first)
        self.mark("checks/anything.py", first)
        result = self.run_map()
        self.assertEqual(result["layers"], ["domain", "unused", "api", "empty", ".", "b"])
        rows = self.rows(result)
        self.assertEqual(rows[first]["code"],
                         {"domain": 2, "unused": 0, "api": 1, "empty": 0, ".": 1, "b": 1})
        self.assertEqual(rows[first]["tests"], 6)
        self.assertEqual(rows[second]["code"],
                         {"domain": 1, "unused": 0, "api": 0, "empty": 0, ".": 0, "b": 0})
        self.config(tests=["verify.*"])
        self.mark("z/verify.rb", first)
        rows = self.rows(self.run_map())
        self.assertEqual(rows[first]["code"]["domain"], 7)
        self.assertEqual(rows[first]["tests"], 2)

    def test_scope_keeps_rules_and_marked_work_but_not_workflow_navigation(self):
        for path in ("README.md", "AGENTS.md", ".agents/local.md", "docs/feature.md",
                     ".agents/lipi/rule.md", "notes/private.md", "workflow/README.md",
                     "workflow/INDEX.md", "workflow/MASTERPLAN.md"):
            self.page(path, "one", "two")
        self.work("workflow/issue/2026/iss-001-unused.md", "open")
        marked = "workflow/issue/2026/iss-002-active.md"
        self.work(marked, "in progress", "", "one", "two")
        self.mark("src/main.py", "ISS-002")
        expected = {"README.md", "AGENTS.md", ".agents/local.md", "docs/feature.md",
                    "ISS-002", marked + "#one", marked + "#two"}
        rows = self.rows(self.run_map())
        self.assertEqual(set(rows), expected)
        self.assertEqual(rows["ISS-002"]["kind"], "work")
        self.assertEqual(rows[marked + "#one"]["status"], "in progress")
        self.config(docs=".")
        self.assertEqual(set(self.rows(self.run_map())), expected | {"notes/private.md"})

    def test_archive_code_does_not_add_places_or_layers(self):
        self.config(workflow="work", decisions="decisions")
        target = "docs/feature.md#one"
        self.page("docs/feature.md", "one")
        for path in ("history/old.py", "work/history/old.py", "decisions/history/old.py",
                     "src/history/current.py"):
            self.mark(path, target)
        result = self.run_map()
        self.assertEqual(result["layers"], ["src"])
        self.assertEqual(self.rows(result)[target]["code"], {"src": 1})

    def test_duplicate_plan_numbers_preserve_statuses_of_explicit_anchors(self):
        plans = {"workflow/plan/2024/pln-101-first.md": "new",
                 "workflow/plan/2025/pln-101-second.md": "in progress"}
        for path, status in plans.items():
            self.work(path, status, "", "scope")
        self.mark("src/scopes.py", *(path + "#scope" for path in plans))
        self.mark("src/ambiguous.py", "PLN-101")
        self.write("neighbor/lipi.json", "{}\n")
        for repos in ({}, {"neighbor": {"path": "neighbor", "read": ["docs"]}}):
            with self.subTest(repos=repos):
                self.config(repos=repos)
                rows = self.rows(self.run_map())
                for path, status in plans.items():
                    anchor = rows[path + "#scope"]
                    self.assertEqual(anchor.get("status"), status)
                    self.assertEqual(anchor["code"], {"src": 1})
                    self.assertEqual(rows[path]["kind"], "work")
                    self.assertEqual(rows[path]["code"], {"src": 0})
                self.assertNotIn("PLN-101", rows)
                code, output = support.cli(self.root, "slice", "PLN-101", "--format", "json")
                self.assertEqual(code, 1, output)
                result = json.loads(output)
                self.assertEqual(result["error"], "ambiguous")
                self.assertEqual({candidate["target"] for candidate in result["candidates"]},
                                 set(plans))

    def test_duplicate_decision_numbers_keep_distinct_paths_and_statuses(self):
        first = "workflow/adr/001-first.md"
        second = "workflow/adr/adr-0001-second.md"
        self.work(first, "accepted", "", "one")
        self.work(second, "rejected", "", "two")
        self.mark("src/main.py", "ADR-1")
        rows = self.rows(self.run_map())
        self.assertEqual(set(rows), {first, second})
        for path, status in ((first, "accepted"), (second, "rejected")):
            self.assertEqual(rows[path]["kind"], "decision")
            self.assertEqual(rows[path]["status"], status)
            self.assertEqual(sum(rows[path]["code"].values()), 0)
            self.assertEqual(rows[path]["tests"], 0)

    def test_git_project_never_reads_blame(self):
        self.config(skip_dirs=["generated"])
        self.page("docs/feature.md", "used")
        self.page("docs/ignored.md", "used")
        self.page("docs/generated/skipped.md", "used")
        self.write(".gitignore", "docs/ignored.md\n")
        self.mark("src/main.py", "docs/feature.md#used", "docs/ignored.md#used",
                  "docs/generated/skipped.md#used")
        self.mark("generated/main.py", "docs/feature.md#used")
        support.git_init(self.root)
        code, out = support.commit(self.root)
        self.assertEqual(code, 0, out)
        with tempfile.TemporaryDirectory(prefix="lipi-map-git-") as directory:
            wrapper = Path(directory) / "git"
            log = Path(directory) / "calls.jsonl"
            support.w(wrapper, "#!" + sys.executable + "\n"
                      "import json, os, sys\n"
                      "with open(%r, 'a') as stream:\n"
                      "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                      "os.execv(%r, ['git', *sys.argv[1:]])\n" %
                      (str(log), shutil.which("git")))
            wrapper.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ.get("PATH", ""))
            code, out = support.run(support.PY + [str(support.CLI), "map", "--format", "json"],
                                    cwd=str(self.root), env=env)
            self.assertEqual(code, 0, out)
            rows = self.rows(json.loads(out))
            self.assertEqual(set(rows), {"docs/feature.md#used"})
            self.assertEqual(rows["docs/feature.md#used"]["code"], {"src": 1})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(calls)
            self.assertFalse(any({"blame", "log", "show", "rev-list"} & set(args)
                                 for args in calls), calls)

    def test_help_and_invalid_arguments(self):
        code, out = support.cli(self.root, "help", "map")
        self.assertEqual(code, 0, out)
        self.assertIn("--format", out)
        for args in (("target",), ("--format", "github"), ("--full",),
                     ("--layer", "src"), ("--depth", "2")):
            with self.subTest(args=args):
                code, out = support.cli(self.root, "map", *args)
                self.assertEqual(code, 2, out)
                self.assertNotIn("Traceback", out)

    def test_invalid_config_is_c1_with_exit_two(self):
        for config in ('{"layers": []}', '{"tests": "test_*"}',
                       '{"entry": ["["]}', '{broken'):
            with self.subTest(config=config):
                self.write("lipi.json", config)
                for fmt in ("text", "json"):
                    code, out = support.cli(self.root, "map", "--format", fmt)
                    self.assertEqual(code, 2, out)
                    self.assertNotIn("Traceback", out)
                    if fmt == "json":
                        self.assertEqual(json.loads(out)["errors"][0]["code"], "C1")
                    else:
                        self.assertIn("C1", out)

    def test_read_only_without_running_project_checks(self):
        self.page("docs/feature.md", "used", "unused")
        self.mark("src/main.py", "docs/feature.md#used")
        self.write("workflow/INDEX.md", "Preserve stale index bytes.\n")
        self.write(".agents/lipi/baseline.json", '{"schema":1,"entries":[]}\n')
        self.config(checks=[{"name": "write sentinel", "mode": "quick", "run": [
            sys.executable, "-c", "open('sentinel','w').write('ran')"]}])
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        self.run_map()
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
