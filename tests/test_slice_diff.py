"""CLI contract for diff slices: review links, snapshot isolation and output bounds."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import support


TARGET = "docs/pricing.md#threshold"
OTHER = "docs/pricing.md#rounding"


class SliceDiffContract(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-diff-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.write("lipi.json", "{}\n")
        self.write("docs/pricing.md", '# Prices\n\n## Threshold <a id="threshold"></a>\n\n'
                   'Threshold rule.\n\n## Rounding <a id="rounding"></a>\n\nRounding rule.\n')

    def write(self, path, text):
        support.w(self.root / path, text)

    def mark(self, path, targets=(TARGET,), symbol="def discount():"):
        self.write(path, "".join("# %s %s\n" % (support.TAG, target) for target in targets) +
                   symbol + "\n    return 0\n")

    def baseline(self):
        support.git_init(self.root)
        code, out = support.commit(self.root, "baseline")
        self.assertEqual(code, 0, out)

    def change(self, path):
        support.sub(self.root / path, "return 0", "return 1")

    def stage_change(self, path):
        self.change(path)
        code, out = support.git(self.root, "add", "--", path)
        self.assertEqual(code, 0, out)

    def run_slice(self, *args, expected=0, env=None):
        code, out = support.run(support.PY + [str(support.CLI), "slice", "--format", "json", *args],
                                cwd=str(self.root), env=env)
        self.assertEqual(code, expected, out)
        try:
            return json.loads(out)
        except ValueError:
            self.fail("slice must return JSON: " + out)

    def items(self, result, kind):
        return next((block["items"] for block in result["blocks"] if block["kind"] == kind), [])

    def assert_place_labels(self, args, expected):
        code, text = support.cli(self.root, "slice", *args)
        self.assertEqual(code, 0, text)
        via = support.localized(" — via ", " — через ")
        for path, label in expected.items():
            rows = [line.strip() for line in text.splitlines() if line.lstrip().startswith(path + ":")]
            self.assertEqual(len(rows), 1, text)
            self.assertEqual(rows[0].partition(via)[2], label, rows[0])

    def test_shared_concepts_collect_related_places_obey_and_context_once(self):
        rule = ".agents/architecture.md#money"
        self.write(".agents/architecture.md", '# Money <a id="money"></a>\n')
        self.write("workflow/adr/adr-001-money.md", "# Money policy\n\n"
                   "- Created: 2026-01-01\n- Updated: 2026-01-01\n"
                   "- Status: accepted\n\n## Decision\n\n"
                   "[Threshold](../../docs/pricing.md#threshold).\n"
                   "[Rounding](../../docs/pricing.md#rounding).\n")
        self.write("docs/orders.md", '# Orders <a id="orders"></a>\n\n'
                   '[Threshold](pricing.md#threshold) and [rounding](pricing.md#rounding).\n')
        self.mark("src/changed_a.py", (TARGET, OTHER, rule))
        self.mark("src/changed_b.py", (TARGET,))
        self.mark("src/consumer.py", (TARGET, OTHER))
        self.mark("src/api.py", (TARGET,), "def submit_order():")
        self.mark("tests/test_prices.py", (TARGET, OTHER), "def test_prices():")
        support.set_config(self.root, entry=["submit_order"])
        self.baseline()
        self.change("src/changed_a.py")
        self.change("src/changed_b.py")

        result = self.run_slice("--diff", "HEAD")
        self.assertEqual(result["schema"], 1)
        self.assertEqual((result["target"]["kind"], result["target"]["target"]),
                         ("diff", "--diff HEAD"))
        self.assertEqual([block["kind"] for block in result["blocks"]],
                         ["obey", "concepts", "entry", "code", "tests", "context"])
        concepts = [item["target"] for item in self.items(result, "concepts")]
        self.assertEqual(concepts.count(TARGET), 1)
        self.assertEqual(concepts.count(OTHER), 1)
        self.assertEqual([item["path"] for item in self.items(result, "code")], ["src/consumer.py"])
        self.assertEqual([item["path"] for item in self.items(result, "entry")], ["src/api.py"])
        self.assertEqual([item["path"] for item in self.items(result, "tests")], ["tests/test_prices.py"])
        obey = [item["target"] for item in self.items(result, "obey")]
        self.assertEqual(obey.count("ADR-001"), 1)
        self.assertEqual(obey.count(rule), 1)
        context = [item["target"] for item in self.items(result, "context")]
        self.assertEqual(len(context), len(set(context)))
        self.assertTrue(any(item.startswith("docs/orders.md") for item in context), context)
        self.assertEqual(result["checks"]["diff"], {"mode": "diff", "base": "HEAD", "files": 2, "unmarked": 0})
        self.assertEqual(result["summary"]["decisions"], 1)
        self.assertEqual(result["summary"]["rules"], 1)
        self.assertEqual(result["summary"]["code"], 2)
        self.assertEqual(result["summary"]["tests"], 1)
        for kind in ("entry", "code", "tests"):
            for item in self.items(result, kind):
                self.assertTrue({"path", "line", "symbol", "layer"} <= item.keys())
                if kind != "tests":
                    self.assertIn("via", item)

    def test_via_matches_published_1_1_0_with_two_targets(self):
        self.write("docs/api.md", '# API\n\n## Read <a id="read-record"></a>\n\n'
                   '## Summary <a id="summary"></a>\n')
        read_record, summary = "docs/api.md#read-record", "docs/api.md#summary"
        targets = (summary, read_record)
        support.set_config(self.root, entry=["def route"])
        self.mark("src/provider.py", targets)
        self.mark("src/reader.py", targets)
        self.mark("src/read_only.py", (read_record, TARGET))
        self.mark("src/router.py", targets, "def route():")
        self.mark("tests/test_reader.py", targets, "def test_read():")
        self.mark("tests/test_summary.py", (summary, summary), "def test_summary():")
        self.baseline()
        self.stage_change("src/provider.py")

        expected = {
            "entry": {"src/router.py": [read_record, summary]},
            "code": {"src/reader.py": [read_record, summary], "src/read_only.py": [read_record]},
            "tests": {"tests/test_reader.py": [read_record, summary], "tests/test_summary.py": [summary]},
        }
        for args in (("--diff", "HEAD"), ("--staged",)):
            with self.subTest(args=args):
                result = self.run_slice(*args)
                self.assertEqual(result["schema"], 1)
                for kind, by_path in expected.items():
                    items = self.items(result, kind)
                    self.assertEqual(len(items), len(by_path))
                    self.assertEqual({item["path"]: item["matched_targets"] for item in items}, by_path)
                    for item in items:
                        if kind == "tests":
                            self.assertNotIn("via", item)
                        else:
                            self.assertEqual(item["via"], "docs/api.md#read-record")
                self.assert_place_labels(args, {
                    "src/router.py": "#read-record, #summary",
                    "src/reader.py": "#read-record, #summary",
                    "src/read_only.py": "#read-record",
                    "tests/test_reader.py": "#read-record, #summary",
                    "tests/test_summary.py": "#summary",
                })

    def test_one_diff_target_has_json_matches_without_text_labels(self):
        support.set_config(self.root, entry=["def route"])
        self.mark("src/provider.py")
        self.mark("src/router.py", (OTHER, TARGET), "def route():")
        self.mark("src/reader.py", (OTHER, TARGET))
        self.mark("tests/test_reader.py", (OTHER, TARGET), "def test_read():")
        self.baseline()
        self.stage_change("src/provider.py")

        for args in (("--diff", "HEAD"), ("--staged",)):
            with self.subTest(args=args):
                result = self.run_slice(*args)
                for kind in ("entry", "code", "tests"):
                    item, = self.items(result, kind)
                    self.assertEqual(item["matched_targets"], [TARGET])
                    if kind == "tests":
                        self.assertNotIn("via", item)
                    else:
                        self.assertEqual(item["via"], TARGET)
                self.assert_place_labels(args, {
                    "src/router.py": "", "src/reader.py": "", "tests/test_reader.py": "",
                })

        for query, via in ((TARGET, TARGET), ("docs/pricing.md", OTHER), ("src/provider.py", TARGET)):
            with self.subTest(query=query):
                result = self.run_slice(query)
                places = {item["path"]: item for kind in ("entry", "code", "tests")
                          for item in self.items(result, kind)}
                for path in ("src/router.py", "src/reader.py"):
                    self.assertEqual(places[path]["via"], via)
                self.assertNotIn("via", places["tests/test_reader.py"])
                self.assertTrue(all("matched_targets" not in item for item in places.values()))
                self.assert_place_labels((query,), {
                    "src/router.py": "", "src/reader.py": "", "tests/test_reader.py": "",
                })

    def test_anchor_collisions_use_full_addresses_before_filters_and_budget(self):
        neighbor = self.root.parent / "neighbor"
        support.w(neighbor / "lipi.json", "{}\n")
        support.w(neighbor / "docs/pricing.md", '# Neighbor prices\n\n'
                  '## Rounding <a id="rounding"></a>\n')
        support.git_init(neighbor)
        code, out = support.commit(neighbor)
        self.assertEqual(code, 0, out)
        self.write("docs/checkout.md", '# Checkout\n\n## Threshold <a id="threshold"></a>\n')
        checkout = "docs/checkout.md#threshold"
        external = "neighbor::docs/pricing.md#rounding"
        support.set_config(self.root, repos={"neighbor": {"path": "../neighbor", "read": ["docs"]}},
                           layers={"src/a_visible.py": "domain", "src/b_local.py": "client"}, slice_budget=4)
        self.mark("src/provider.py", (TARGET, OTHER, checkout, external))
        self.mark("src/a_visible.py", (OTHER,))
        self.mark("src/b_local.py", (TARGET, checkout))
        self.mark("tests/test_neighbor.py", (external, OTHER))
        self.baseline()
        self.stage_change("src/provider.py")

        for args in (("--diff", "HEAD"), ("--staged",)):
            with self.subTest(args=args):
                filtered = (*args, "--only", "code,tests")
                result = self.run_slice(*filtered)
                local, both = self.items(result, "code")
                self.assertEqual((local["path"], local["via"], local["matched_targets"]),
                                 ("src/a_visible.py", OTHER, [OTHER]))
                self.assertEqual((both["path"], both["via"], both["matched_targets"]),
                                 ("src/b_local.py", checkout, [checkout, TARGET]))
                test_item, = self.items(result, "tests")
                self.assertEqual(test_item["matched_targets"], [OTHER, external])
                self.assert_place_labels(filtered, {
                    "src/a_visible.py": OTHER,
                    "src/b_local.py": checkout + ", " + TARGET,
                    "tests/test_neighbor.py": OTHER + ", " + external,
                })
                self.assert_place_labels((*args, "--only", "code", "--layer", "domain"), {
                    "src/a_visible.py": OTHER,
                })
                limited = self.run_slice(*args)
                self.assertTrue(limited["incomplete"])
                self.assertEqual([item["path"] for item in self.items(limited, "code")], ["src/a_visible.py"])
                self.assertFalse(any(item["repo"] for item in self.items(limited, "concepts")))
                self.assert_place_labels(args, {"src/a_visible.py": OTHER})

    def test_labels_use_address_for_target_without_anchor(self):
        self.write("workflow/adr/adr-001-prices.md", "# Prices\n\n- Status: accepted\n")
        self.mark("src/provider.py", (TARGET, "ADR-001"))
        self.mark("src/reader.py", (TARGET, "adr-1"))
        self.baseline()
        self.change("src/provider.py")

        args = ("--diff", "HEAD")
        item, = self.items(self.run_slice(*args), "code")
        self.assertEqual(item["matched_targets"], ["ADR-001", TARGET])
        self.assert_place_labels(args, {"src/reader.py": "ADR-001, #threshold"})

    def test_changes_prompt_review_without_asserting_related_code_is_wrong(self):
        self.mark("src/changed.py")
        self.mark("src/consumer.py")
        self.write("src/plain.py", "VALUE = 0\n")
        self.baseline()
        self.change("src/changed.py")
        self.write("src/plain.py", "VALUE = 1\n")
        result = self.run_slice("--diff", "HEAD")
        notes = {note["code"]: note["text"] for note in result["notes"]}
        self.assertEqual(notes["diff-review"], "check related locations, decisions, and tests")
        self.assertEqual(notes["diff-unmarked"], "changes without trace markers: 1 location")
        self.assertEqual(result["checks"]["diff"]["unmarked"], 1)
        self.assertFalse(self.items(result, "signals"))
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 0)
        code, text = support.cli(self.root, "slice", "--diff", "HEAD")
        self.assertEqual(code, 0, text)
        self.assertIn(support.localized(notes["diff-review"],
                                        "проверьте связанные места, решения и тесты"), text)
        self.assertIn(support.localized(notes["diff-unmarked"],
                                        "изменения без меток: 1 место"), text)

    def test_staged_uses_index_marks_even_when_worktree_has_other_marks(self):
        self.mark("src/changed.py")
        self.mark("src/threshold_consumer.py")
        self.mark("src/rounding_consumer.py", (OTHER,))
        self.baseline()
        self.change("src/changed.py")
        code, out = support.git(self.root, "add", "src/changed.py")
        self.assertEqual(code, 0, out)
        support.sub(self.root / "src/changed.py", TARGET, OTHER)
        staged = self.run_slice("--staged")
        self.assertEqual(staged["target"]["target"], "--staged")
        self.assertEqual([item["target"] for item in self.items(staged, "concepts")], [TARGET])
        self.assertEqual([item["path"] for item in self.items(staged, "code")], ["src/threshold_consumer.py"])
        self.assertEqual(staged["checks"]["diff"], {"mode": "staged", "base": None, "files": 1, "unmarked": 0})
        worktree = self.run_slice("--diff", "HEAD")
        self.assertEqual({item["target"] for item in self.items(worktree, "concepts")}, {TARGET, OTHER})

    def test_diff_excludes_archive_changes_with_repos(self):
        self.write("neighbor/lipi.json", "{}\n")
        support.set_config(self.root, workflow="work", decisions="decisions",
                           repos={"neighbor": {"path": "neighbor", "read": ["docs"]}})
        archives = ("history/old.py", "work/history/old.py", "decisions/history/old.py")
        for path in archives:
            self.mark(path)
        current = "src/history/current.py"
        self.mark(current, (OTHER,))
        self.baseline()
        for path in (*archives, current):
            self.change(path)
        code, out = support.git(self.root, "add", "--", *archives, current)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.items(self.run_slice(TARGET), "code"), [])
        for args, mode, base in ((["--staged"], "staged", None), (["--diff", "HEAD"], "diff", "HEAD")):
            with self.subTest(mode=mode):
                result = self.run_slice(*args)
                self.assertEqual([item["target"] for item in self.items(result, "concepts")], [OTHER])
                self.assertEqual(result["checks"]["diff"],
                                 {"mode": mode, "base": base, "files": 1, "unmarked": 0})

    def test_deleted_code_keeps_old_concept_and_related_test(self):
        self.mark("src/removed.py")
        self.mark("tests/test_discount.py", symbol="def test_discount():")
        self.baseline()
        (self.root / "src/removed.py").unlink()
        result = self.run_slice("--diff", "HEAD")
        self.assertEqual([item["target"] for item in self.items(result, "concepts")], [TARGET])
        self.assertEqual([item["path"] for item in self.items(result, "tests")], ["tests/test_discount.py"])
        self.assertFalse(self.items(result, "code"))
        self.assertEqual(result["checks"]["diff"]["unmarked"], 0)

    def test_changed_marker_retains_real_status_signal_and_only_cannot_hide_it(self):
        self.write("workflow/issue/2026/iss-001-old.md", "# Old workaround\n\n"
                   "- Created: 2026-01-01\n- Updated: 2026-01-01\n"
                   "- Closed: 2026-01-01\n- Status: closed\n- Kind: bug\n\n## Observation\n\nResolved.\n")
        self.mark("src/changed.py", (TARGET, "ISS-001"))
        self.mark("tests/test_discount.py", symbol="def test_discount():")
        self.baseline()
        self.change("src/changed.py")
        result = self.run_slice("--diff", "HEAD", "--only", "tests")
        self.assertEqual([block["kind"] for block in result["blocks"]], ["signals", "tests"])
        statuses = [item for item in self.items(result, "signals") if item["code"] == "T3"]
        self.assertEqual([item["target"] for item in statuses], ["ISS-001"])
        self.assertIn("check whether the link is needed", statuses[0]["message"])
        self.assertEqual(result["summary"]["warnings"], 1)
        support.set_config(self.root, codes={"T3": "off"})
        disabled = self.run_slice("--diff", "HEAD", "--only", "tests")
        self.assertFalse(self.items(disabled, "signals"))
        self.assertEqual(disabled["summary"]["warnings"], 0)

    def test_empty_diff_is_success_and_untracked_code_is_not_a_change(self):
        self.mark("src/unchanged.py")
        self.baseline()
        self.mark("src/untracked.py", (OTHER,))
        for args, mode, base in ((["--diff", "HEAD"], "diff", "HEAD"), (["--staged"], "staged", None)):
            with self.subTest(mode=mode):
                result = self.run_slice(*args)
                self.assertEqual(result["checks"]["diff"], {"mode": mode, "base": base, "files": 0, "unmarked": 0})
                self.assertFalse(any(block["items"] for block in result["blocks"]))
                self.assertFalse(result["incomplete"])

    def test_modes_are_exclusive_and_git_failures_are_machine_readable(self):
        for args in ((), (TARGET, "--diff", "HEAD"), (TARGET, "--staged"),
                     ("--diff", "HEAD", "--staged"), ("--diff",)):
            with self.subTest(args=args):
                code, out = support.cli(self.root, "slice", *args)
                self.assertEqual(code, 2, out)
        for args in (("--diff", "HEAD"), ("--staged",)):
            result = self.run_slice(*args, expected=2)
            self.assertEqual(result["error"], "invalid-diff")
        self.baseline()
        invalid = self.run_slice("--diff", "missing-base", expected=2)
        self.assertEqual(invalid["error"], "invalid-diff")
        env = dict(os.environ, PATH=str(self.root / "no-executables"))
        missing_git = self.run_slice("--diff", "HEAD", expected=2, env=env)
        self.assertEqual(missing_git["error"], "invalid-diff")

    def test_budget_and_filters_preserve_same_selection_in_text_and_json(self):
        self.mark("src/changed.py")
        for number in range(8):
            self.mark("src/consumer_%02d.py" % number)
            self.mark("tests/test_consumer_%02d.py" % number)
        support.set_config(self.root, slice_budget=9, layers={"src/*": "domain", "tests/*": "tests"})
        self.baseline()
        self.change("src/changed.py")
        result = self.run_slice("--diff", "HEAD")
        self.assertTrue(result["incomplete"])
        self.assertLessEqual(sum(len(block["items"]) for block in result["blocks"]), 9)
        self.assertEqual((result["summary"]["code"], result["summary"]["tests"]), (8, 8))
        self.assertTrue(self.items(result, "tests"))
        code, text = support.cli(self.root, "slice", "--diff", "HEAD")
        self.assertEqual(code, 0, text)
        selected = {item["path"] for kind in ("code", "tests") for item in self.items(result, kind)}
        for kind, pattern in (("src", "consumer_*.py"), ("tests", "test_consumer_*.py")):
            for path in (self.root / kind).glob(pattern):
                relative = str(path.relative_to(self.root))
                self.assertEqual(relative + ":1" in text, relative in selected, text)
        only = self.run_slice("--diff", "HEAD", "--only", "tests")
        self.assertEqual([block["kind"] for block in only["blocks"]], ["tests"])
        self.assertEqual(len(self.items(only, "tests")), 8)
        self.assertEqual(only["summary"], result["summary"])
        layer = self.run_slice("--diff", "HEAD", "--layer", "domain")
        self.assertFalse(self.items(layer, "tests"))
        self.assertEqual(layer["summary"]["tests"], 0)
        self.assertEqual(layer["summary"]["code"], 8)

    def test_diff_does_not_mutate_worktree_index_or_baseline(self):
        self.mark("src/changed.py")
        self.mark("src/consumer.py")
        self.write("workflow/INDEX.md", "Hand-maintained index.\n")
        self.write(".agents/lipi/baseline.json", '{"schema": 1, "entries": []}\n')
        self.baseline()
        self.change("src/changed.py")
        code, out = support.git(self.root, "add", "src/changed.py")
        self.assertEqual(code, 0, out)

        def snapshot():
            return {str(path.relative_to(self.root)): path.read_bytes()
                    for path in self.root.rglob("*")
                    if path.is_file() and ".git" not in path.relative_to(self.root).parts}

        before = snapshot()
        git_index = (self.root / ".git/index").read_bytes()
        for args in (("--diff", "HEAD"), ("--staged",)):
            self.run_slice(*args)
        self.assertEqual(snapshot(), before)
        self.assertEqual((self.root / ".git/index").read_bytes(), git_index)


if __name__ == "__main__":
    unittest.main()
