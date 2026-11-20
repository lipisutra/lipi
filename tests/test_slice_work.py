"""Work slices inherit obligations from direct goals without nested slices."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import support


class WorkSliceContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-work-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("lipi.json", '{"codes": {"A4": "off"}}\n')
        self.write("docs/guide.md", '# Guide\n\n## First <a id="first"></a>\n\nFirst.\n\n'
                   '## Second <a id="second"></a>\n\nSecond.\n\n'
                   '## Empty <a id="empty"></a>\n\nEmpty.\n')

    def write(self, path, text):
        support.w(self.root / path, text)

    def work(self, kind, number, status, body="", header=""):
        aid = "%s-%03d" % (kind.upper(), number)
        path = "workflow/%s/%s-item.md" % (support.TYPE_DIRS[kind], aid.lower())
        self.write(path, "# %s\n\n- Created: 2026-11-18\n"
                   "- Updated: 2026-11-18\n- Status: %s\n%s\n%s\n"
                   % (aid, status, header, body))
        return path

    def plan(self, links):
        self.work("pln", 1, "new", "\n".join("[Goal](%s)" % link for link in links))

    def mark(self, path, *targets):
        self.write(path, "# %s %s\ndef example():\n    return 0\n" %
                   (support.TAG, ",".join(targets)))

    def run_slice(self, *args):
        code, output = support.cli(self.root, "slice", "PLN-001", "--format", "json", *args)
        self.assertEqual(code, 0, output)
        return json.loads(output)

    @staticmethod
    def items(response, kind):
        return [item for block in response["blocks"] if block["kind"] == kind
                for item in block["items"]]

    # @trace docs/ru/slice.md#blocks,docs/ru/slice.md#summary,docs/ru/slice.md#json
    def test_shared_decision_and_rules_keep_all_sources_without_expanding_code(self):
        first, second = "docs/guide.md#first", "docs/guide.md#second"
        self.plan(["../../" + first, "../../" + second, "../../docs/guide.md#empty"])
        self.work("adr", 1, "accepted", "[First](../../%s)\n[Second](../../%s)" % (first, second))
        self.write("AGENTS.md", '# Rules\n\n## Rule <a id="rule"></a>\n[First](%s)\n' % first)
        self.write(".agents/custom.md", '# Custom\n\n## Custom <a id="rule"></a>\n')
        self.mark("src/first.py", first, ".agents/custom.md#rule")
        self.mark("src/second.py", second, ".agents/custom.md#rule")
        self.mark("src/plan.py", "PLN-001")
        result = self.run_slice()
        obey = self.items(result, "obey")
        self.assertEqual([item["target"] for item in obey],
                         ["ADR-001", ".agents/custom.md#rule", "AGENTS.md#rule"])
        self.assertEqual([item["via"] for item in obey], [[first, second], [first, second], [first]])
        self.assertEqual([item["relation"] for item in obey], ["link", "mark", "link"])
        place, = self.items(result, "code")
        self.assertEqual((place["path"], place["via"]), ("src/plan.py", "PLN-001"))
        self.assertNotIn("matched_targets", place)
        self.assertEqual(result["summary"]["decisions"], 1)
        self.assertEqual(result["summary"]["rules"], 2)
        self.assertEqual(result["summary"]["targets"], 3)
        self.assertEqual([block["kind"] for block in result["blocks"]], ["obey", "code", "targets"])
        code, text = support.cli(self.root, "slice", "PLN-001", "--only", "code")
        self.assertEqual(code, 0, text)
        self.assertIn("src/plan.py:", text)
        self.assertNotIn(support.localized(" — via ", " — через "), text)

    # @trace docs/ru/slice.md#blocks
    def test_goal_without_obligations_keeps_old_empty_and_target_behavior(self):
        self.plan(["../../docs/guide.md#empty"])
        self.mark("src/other.py", "docs/guide.md#empty")
        result = self.run_slice()
        self.assertEqual(self.items(result, "obey"), [])
        self.assertEqual(self.items(result, "code"), [])
        self.assertEqual(self.items(result, "targets")[0]["code_count"], 1)
        self.assertNotIn("work-empty", [note["code"] for note in result["notes"]])

    # @trace docs/ru/slice.md#blocks
    def test_page_goals_use_anchors_and_preserve_direct_work_obligations(self):
        self.plan(["../../docs/guide.md"])
        self.work("adr", 1, "accepted", "[First](../../docs/guide.md#first)")
        self.work("adr", 2, "accepted", "[Plan](../plan/pln-001-item.md)")
        self.write("AGENTS.md", '# Rules\n\n## Own <a id="own"></a>\n')
        self.mark("src/plan.py", "PLN-001", "AGENTS.md#own")
        result = self.run_slice()
        obey = {item["target"]: item["via"] for item in self.items(result, "obey")}
        self.assertEqual(obey, {"ADR-001": ["docs/guide.md"], "ADR-002": ["PLN-001"],
                                "AGENTS.md#own": ["PLN-001"]})

    # @trace docs/ru/slice.md#blocks
    def test_direct_decision_inherits_bases_and_refinements_without_siblings(self):
        self.work("adr", 1, "accepted")
        self.work("adr", 2, "accepted", header="- Refines: [ADR-001](adr-001-item.md)")
        self.work("adr", 3, "accepted", header="- Refines: [ADR-001](adr-001-item.md)")
        self.work("adr", 4, "accepted", header="- Refines: [ADR-002](adr-002-item.md)")
        self.work("adr", 5, "accepted", "[Ordinary](adr-002-item.md)")
        self.plan(["../adr/adr-002-item.md"])
        result = self.run_slice()
        obey = self.items(result, "obey")
        self.assertEqual([item["target"] for item in obey], ["ADR-001", "ADR-002", "ADR-004"])
        self.assertTrue(all(item["via"] == ["ADR-002"] for item in obey))

    # @trace docs/ru/slice.md#blocks
    def test_inactive_decisions_are_signals_and_stop_refinement_branches(self):
        self.plan(["../../docs/guide.md#first", "../adr/adr-004-item.md"])
        self.work("adr", 1, "superseded", "[First](../../docs/guide.md#first)",
                  header="- Result: [ADR-002](adr-002-item.md)")
        self.work("adr", 2, "accepted", header="- Refines: [ADR-001](adr-001-item.md)")
        self.work("adr", 3, "rejected", "[First](../../docs/guide.md#first)")
        self.work("adr", 4, "rejected")
        result = self.run_slice()
        self.assertEqual(self.items(result, "obey"), [])
        self.assertEqual({item["target"] for item in self.items(result, "signals")
                          if item["code"] == "T3"}, {"ADR-001", "ADR-003", "ADR-004"})
        self.assertEqual(result["summary"]["warnings"], 3)

    # @trace docs/ru/slice.md#blocks
    def test_goal_links_to_retired_decisions_keep_status_signal(self):
        self.plan(["../../docs/guide.md#first"])
        self.work("adr", 1, "rejected")
        self.write("docs/guide.md", '# Guide\n\n## First <a id="first"></a>\n\n'
                   '[Prior rule](../workflow/adr/adr-001-item.md).\n')
        result = self.run_slice()
        self.assertEqual(self.items(result, "obey"), [])
        signals = self.items(result, "signals")
        self.assertEqual(len(signals), 1)
        self.assertEqual((signals[0]["code"], signals[0]["target"], signals[0]["path"]),
                         ("T3", "ADR-001", "docs/guide.md"))
        self.assertIn("whether the text is still current", signals[0]["message"])

    # @trace docs/ru/slice-diff.md#response,docs/ru/slice.md#blocks
    def test_diff_work_marker_inherits_goal_obligations_without_goal_code(self):
        self.work("iss", 1, "open", "[Goal](../../docs/guide.md#first)")
        self.work("adr", 1, "accepted", "[Goal](../../docs/guide.md#first)")
        self.mark("src/issue.py", "ISS-001")
        self.mark("src/related.py", "ISS-001")
        self.mark("src/concept.py", "docs/guide.md#first")
        support.git_init(self.root)
        code, output = support.commit(self.root, "initial")
        self.assertEqual(code, 0, output)
        path = self.root / "src/issue.py"
        self.write("src/issue.py", path.read_text().replace("return 0", "return 1"))
        code, output = support.cli(self.root, "slice", "--diff", "HEAD", "--format", "json")
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual([item["target"] for item in self.items(result, "concepts")], ["ISS-001"])
        self.assertEqual([item["target"] for item in self.items(result, "obey")], ["ADR-001"])
        self.assertEqual([item["path"] for item in self.items(result, "code")], ["src/related.py"])

    # @trace docs/ru/slice.md#budget,docs/ru/slice.md#summary
    def test_budget_and_only_preserve_full_obligation_counts(self):
        self.plan(["../../docs/guide.md#first"])
        for number in range(1, 8):
            self.work("adr", number, "accepted", "[First](../../docs/guide.md#first)")
        support.set_config(self.root, slice_budget=2, codes={"A4": "off"})
        result = self.run_slice("--only", "obey")
        self.assertEqual(len(self.items(result, "obey")), 2)
        self.assertEqual(result["summary"]["decisions"], 7)
        self.assertEqual(result["blocks"][0]["omitted"], 5)
        self.assertTrue(result["incomplete"])


if __name__ == "__main__":
    unittest.main()
