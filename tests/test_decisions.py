"""ADR-015: decision identity, validation, links and refinement contracts."""
import json
import tempfile
from pathlib import Path

from tests import support


# @trace docs/ru/codes.md#t1,docs/ru/codes.md#d6,ADR-015
class DecisionContracts(support.Case):
    def decision(self, root, name="0001-base.md", status="accepted", header="", body="",
                 directory="docs/adr"):
        path = root / directory / name
        closed = "- Closed: 2026-11-01\n" if status in ("superseded", "rejected") else ""
        support.w(path, "# Decision " + name + "\n\n- Created: 2026-11-01\n"
                  "- Updated: 2026-11-01\n- Status: " + status + "\n" + closed + header +
                  "\n## Контекст\n\nReason.\n\n## Decision\n\nRule.\n" + body)
        return path

    def configured(self, **config):
        root = self.project()
        support.set_config(root, decisions="docs/adr", **config)
        return root

    def bare(self):
        tmp = tempfile.TemporaryDirectory(prefix="lipi-decisions-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        support.w(root / "lipi.json", json.dumps({"workflow": None, "decisions": "decisions"}))
        return root

    def findings(self, root, *args):
        code, result = support.check_json(root, *args)
        self.assertIsNotNone(result)
        self.assertNotEqual(code, 2, result)
        return result["errors"] + result["warnings"]

    def slice(self, root, target, expected=0):
        code, out = support.cli(root, "slice", target, "--format", "json", "--full")
        self.assertEqual(code, expected, out)
        return json.loads(out)

    @staticmethod
    def items(result, kind):
        return [item for block in result.get("blocks", []) if block["kind"] == kind
                for item in block["items"]]

    def test_filename_and_reference_aliases_share_one_canonical_identity(self):
        root = self.configured()
        aliases = ("ADR-1", "ADR-0001", "adr-001")
        support.w(root / "src/order.py", "".join(
            "# %s %s\nvalue_%d = 1\n" % (support.TAG, alias, n)
            for n, alias in enumerate(aliases)))
        with (root / "docs/guide.md").open("a") as stream:
            stream.write("\n<!-- covers: " + ", ".join(aliases) + " -->\n")
        previous = None
        for name in ("001-base.md", "0001-base.md", "adr-001-base.md"):
            with self.subTest(filename=name):
                if previous:
                    previous.unlink()
                    index = root / "workflow/INDEX.md"
                    if index.exists():
                        support.w(index, index.read_text().replace(previous.name, name))
                previous = self.decision(root, name)
                code, result = support.check_json(root, "--structure")
                self.assertEqual(code, 0, result)
                edges = result["structure"]["edges"]
                self.assertEqual({edge["to"] for edge in edges
                                  if edge["type"] in ("trace", "covers")}, {"ADR-001"})
                for alias in aliases:
                    with self.subTest(alias=alias):
                        result = self.slice(root, alias)
                        self.assertEqual(result["target"]["target"], "ADR-001")
                        self.assertEqual(result["target"]["kind"], "decision")
                        self.assertEqual(len(self.items(result, "code")), 3)

    def test_duplicate_numbers_are_errors_and_slice_returns_paths(self):
        root = self.configured()
        paths = [self.decision(root, name) for name in ("001-first.md", "adr-0001-second.md")]
        support.w(root / "src/order.py", "# %s ADR-0001\nvalue = 1\n" % support.TAG)
        with (root / "docs/guide.md").open("a") as stream:
            stream.write("\n<!-- covers: ADR-1 -->\n")
        findings = self.findings(root)
        for kind in ("T1", "D6"):
            with self.subTest(kind=kind):
                matches = [item for item in findings if item["code"] == kind]
                self.assertEqual(len(matches), 1, findings)
                self.assertIn('ambiguous', matches[0]["message"])
        result = self.slice(root, "ADR-01", expected=1)
        self.assertEqual(result["error"], "ambiguous")
        self.assertEqual({item["target"] for item in result["candidates"]},
                         {path.relative_to(root).as_posix() for path in paths})

    def test_one_physical_file_seen_by_workflow_and_decisions_is_not_a_duplicate(self):
        root = self.project()
        support.set_config(root, decisions="workflow/adr")
        self.decision(root, "adr-001-base.md", directory="workflow/adr")
        support.w(root / "src/order.py", "# %s ADR-0001\nvalue = 1\n" % support.TAG)
        code, result = support.check_json(root, "--structure")
        self.assertEqual(code, 0, result)
        nodes = [node for node in result["structure"]["nodes"] if node["id"] == "ADR-001"]
        self.assertEqual(len(nodes), 1, nodes)
        self.assertEqual(self.slice(root, "ADR-1")["target"]["target"], "ADR-001")

    def test_explicit_directory_replaces_default_and_works_without_workflow(self):
        root = self.configured(workflow=None)
        self.decision(root)
        self.decision(root, "adr-001-ignored.md", directory="workflow/adr")
        support.w(root / "src/order.py", "# %s ADR-1\nvalue = 1\n" % support.TAG)
        self.assertEqual(self.findings(root), [])
        self.assertEqual(self.slice(root, "ADR-0001")["target"]["target"], "ADR-001")

    def test_decisions_without_docs_are_valid_and_new_keeps_bare_number_width(self):
        root = self.bare()
        self.decision(root, directory="decisions")
        support.w(root / "src/main.py", "# %s ADR-0001\nvalue = 1\n" % support.TAG)
        self.assertEqual(self.findings(root), [])
        self.assertEqual(self.slice(root, "ADR-1")["target"]["target"], "ADR-001")
        code, out = support.cli(root, "new", "adr", "Next rule", "--format", "json")
        self.assertEqual(code, 0, out)
        result = json.loads(out)
        self.assertEqual(result["id"], "ADR-002")
        created = list((root / "decisions").glob("0002-*.md"))
        self.assertEqual(len(created), 1, result)
        self.assertFalse(list(root.rglob("adr-002-*.md")))
        self.assertFalse(list(root.rglob("INDEX.md")))
        self.decision(root, "003-other.md", directory="decisions")
        code, out = support.cli(root, "new", "adr", "Mixed widths", "--format", "json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["id"], "ADR-004")
        self.assertEqual(len(list((root / "decisions").glob("0004-*.md"))), 1)

    # @trace docs/ru/codes.md#c1
    def test_invalid_decision_directory_stops_configuration(self):
        root = self.project()
        for value in (None, "", "../outside", 7):
            with self.subTest(value=value):
                support.set_config(root, decisions=value)
                code, result = support.check_json(root)
                self.assertEqual(code, 2, result)
                self.assertTrue(any(item["code"] == "C1" and "decisions" in item["message"]
                                    for item in result["errors"]), result)

    def test_nul_decision_directory_returns_configuration_json(self):
        root = self.project()
        support.set_config(root, decisions="bad\x00path")
        for command in (("check",), ("map",), ("slice", "ADR-001")):
            with self.subTest(command=command):
                code, out = support.cli(root, *command, "--format", "json")
                self.assertEqual(code, 2, out)
                self.assertNotIn("Traceback", out)
                result = json.loads(out)
                self.assertTrue(any(item["code"] == "C1" and "decisions" in item["message"]
                                    for item in result["errors"]), result)

    # @trace ADR-015
    def test_unicode_decision_directory_remains_valid(self):
        root = self.project()
        directory = "docs/решения"
        support.set_config(root, decisions=directory)
        self.decision(root, directory=directory)
        self.assertEqual(self.findings(root), [])
        self.assertEqual(self.slice(root, "ADR-1")["target"]["target"], "ADR-001")

    def assert_archived_decision_stays_unresolved(self, root, archived):
        code, result = support.check_json(root, "--structure")
        self.assertEqual(code, 1, result)
        self.assertEqual([(item["code"], item["file"], item["subject"])
                          for item in result["errors"] + result["warnings"]],
                         [("T1", "src/order.py", "ADR-001")])
        nodes = result["structure"]["nodes"]
        self.assertEqual([node["id"] for node in nodes if node["id"].startswith("ADR-")],
                         ["ADR-002"])
        self.assertFalse([node for node in nodes if "/history/" in node.get("path", "")])
        for target in ("ADR-001", archived.relative_to(root).as_posix()):
            self.assertEqual(self.slice(root, target, expected=1)["error"], "not-found")
        self.assertEqual(self.items(self.slice(root, "ADR-002"), "code"), [])
        code, out = support.cli(root, "map", "--format", "json")
        self.assertEqual(code, 0, out)
        rows = json.loads(out)["rows"]
        self.assertEqual([row["target"] for row in rows if row["kind"] == "decision"],
                         ["ADR-002"])
        self.assertFalse([row for row in rows if "/history/" in row["target"]])

    def test_archived_prefixed_decision_number_and_old_trace_are_not_reused(self):
        for layout in ("file", "folder", "whole-workflow"):
            with self.subTest(layout=layout):
                root = self.project()
                directory = "workflow/adr"
                if layout == "folder":
                    directory += "/adr-001-old-rule"
                old = self.decision(root, "adr-001-readme.md", directory=directory)
                support.w(root / "src/order.py", "# %s ADR-001\nvalue = 1\n" % support.TAG)
                history = root / "workflow/history"
                if layout == "whole-workflow":
                    moved = root / "old-workflow"
                    (root / "workflow").rename(moved)
                    history.mkdir(parents=True)
                    moved.rename(history / "old-workflow")
                    archived = history / "old-workflow/adr" / old.name
                else:
                    history.mkdir(parents=True)
                    moved = old.parent if layout == "folder" else old
                    archived = history / moved.name
                    moved.rename(archived)
                    if layout == "folder":
                        archived /= old.name
                support.w(archived, "# Archived rule\n\n[Missing](missing.md)\n")
                support.w(archived.parent / "example.py",
                          "# %s missing-target\nvalue = 1\n" % support.TAG)
                code, out = support.cli(root, "new", "adr", "New rule", "--format", "json")
                self.assertEqual(code, 0, out)
                self.assertEqual(json.loads(out)["id"], "ADR-002")
                self.assertTrue((root / "workflow/adr/adr-002-new-rule.md").is_file())
                self.assert_archived_decision_stays_unresolved(root, archived)

    def test_archived_bare_decisions_preserve_number_and_filename_width(self):
        for layout, width in (("file", 3), ("file", 4), ("folder", 4)):
            with self.subTest(layout=layout, width=width):
                root = self.project()
                support.set_config(root, decisions="decisions")
                number = "1".zfill(width)
                directory = "decisions" + ("/" + number + "-old-rule" if layout == "folder" else "")
                old = self.decision(root, number + "-readme.md", directory=directory)
                support.w(root / "src/order.py", "# %s ADR-001\nvalue = 1\n" % support.TAG)
                archive = root / "workflow/history/decisions"
                archive.mkdir(parents=True)
                moved = old.parent if layout == "folder" else old
                archived = archive / moved.name
                moved.rename(archived)
                if layout == "folder":
                    archived /= old.name
                code, out = support.cli(root, "new", "adr", "New rule", "--format", "json")
                self.assertEqual(code, 0, out)
                self.assertEqual(json.loads(out)["id"], "ADR-002")
                self.assertTrue((root / "decisions" / ("2".zfill(width) + "-new-rule.md")).is_file())
                self.assert_archived_decision_stays_unresolved(root, archived)

    def test_archived_other_work_and_attachments_do_not_allocate_decision_numbers(self):
        root = self.project()
        self.decision(root, "adr-001-current.md", directory="workflow/adr")
        self.decision(root, "0010-readme.md", directory="workflow/history/adr/0010-old-rule")
        for path in ("plan/0090-plan.md", "audit/0091-audit.md", "0092-notes.md",
                     "adr/0010-old-rule/0093-attachment.md", "plan/pln-094-old.md",
                     "audit/aud-095-old.md"):
            support.w(root / "workflow/history" / path, "# Historical material\n")
        code, out = support.cli(root, "new", "adr", "New rule", "--format", "json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["id"], "ADR-011")
        self.assertTrue((root / "workflow/adr/adr-011-new-rule.md").is_file())

    def test_archive_numbering_without_workflow_uses_only_known_decision_names(self):
        for archive, name, created in (
            ("decisions/history", "0001-old.md", "0002-new-rule.md"),
            ("history/old-workflow/adr", "0001-old.md", "0002-new-rule.md"),
            ("history", "adr-001-old.md", "adr-002-new-rule.md"),
        ):
            with self.subTest(archive=archive):
                root = self.bare()
                self.decision(root, name, directory=archive)
                support.w(root / "history/0099-unrelated.md", "# Historical material\n")
                code, out = support.cli(root, "new", "adr", "New rule", "--format", "json")
                self.assertEqual(code, 0, out)
                self.assertEqual(json.loads(out)["id"], "ADR-002")
                self.assertTrue((root / "decisions" / created).is_file())

    def test_folder_decision_has_one_identity_and_attachments_keep_link_validation(self):
        root = self.configured()
        directory = "docs/adr/adr-0001-rule"
        self.decision(root, "adr-0001-readme.md", directory=directory)
        attachment = root / directory / "notes.md"
        support.w(attachment, "# Notes\n\n[Missing](missing.md)\n" + "Detail.\n" * 350)
        support.w(root / "src/order.py", "# %s ADR-1\nvalue = 1\n" % support.TAG)
        findings = self.findings(root)
        self.assertEqual([(item["code"], item["file"]) for item in findings],
                         [("W6", attachment.relative_to(root).as_posix())])
        support.sub(attachment, "missing.md", "adr-0001-readme.md")
        code, result = support.check_json(root, "--structure")
        self.assertEqual(code, 0, result)
        self.assertEqual([node["id"] for node in result["structure"]["nodes"]
                          if node["id"].startswith("ADR-")], ["ADR-001"])
        self.assertEqual(self.slice(root, "ADR-0001")["target"]["target"], "ADR-001")

    def test_external_decision_code_attachments_are_not_project_code(self):
        root = self.bare()
        support.set_config(root, entry=[r'^def example'])
        directory = 'decisions/0001-rule'
        self.decision(root, '0001-readme.md', directory=directory)
        support.w(root / directory / 'example.py',
                  '# %s missing-target\n\n\n\n\ndef example():\n    pass\n' % support.TAG)
        support.w(root / 'src/main.py', '# %s ADR-1\nvalue = 1\n' % support.TAG)
        code, result = support.check_json(root, '--audit', '--structure')
        self.assertEqual(code, 0, result)
        self.assertFalse([item for item in result['errors'] + result['warnings']
                          if item['code'] in ('T1', 'A3')], result)
        self.assertEqual(result['summary']['tags'], 1)
        self.assertEqual([item['path'] for item in self.items(self.slice(root, 'ADR-1'), 'code')],
                         ['src/main.py'])

    def test_bare_decision_folder_attachments_participate_in_graph_and_stale_chain(self):
        root = self.configured()
        directory = 'docs/adr/0001-rule'
        self.decision(root, '0001-readme.md', directory=directory)
        support.w(root / directory / 'notes.md',
                  '# Notes\n\n[Rule](../../guide.md#max-discount)\n')
        code, result = support.check_json(root, '--structure')
        self.assertEqual(code, 0, result)
        self.assertTrue(any(edge['from'] == 'ADR-001' and edge['to'] == 'docs/guide.md'
                            and edge['type'] == 'link'
                            for edge in result['structure']['edges']), result)
        support.git_init(root)
        self.assertEqual(support.commit(root)[0], 0)
        support.sub(root / 'src/order.py', 'def discount(o):', 'def discount(o):\n    return 0')
        self.assertEqual(support.git(root, 'add', 'src/order.py')[0], 0)
        code, result = support.check_json(root, '--staged', '--structure')
        self.assertEqual(code, 0, result)
        self.assertTrue(any(item['anchor'] == 'docs/guide.md#max-discount'
                            and {'id': 'ADR-001', 'status': 'accepted'} in item['works']
                            for item in result['structure']['stale']), result)

    # @trace docs/ru/codes.md#w3,docs/ru/codes.md#w6,docs/ru/codes.md#d2,ADR-015
    def test_decisions_skip_doc_size_and_reachability_but_validate_header_links_and_anchors(self):
        root = self.configured()
        path = self.decision(root, body="\n" + "Detail.\n" * 350)
        self.assertEqual(self.findings(root), [])
        for replacement, expected in (
            (("- Status: accepted", "**Status:** accepted"), "W3"),
            (("- Status: accepted", "- Status: уточнено"), "W3"),
            (("- Status: accepted", "- Status: accepted\n- Refines: ADR-001"), "W3"),
            (("Rule.", "[Missing](missing.md)"), "W6"),
            (("Rule.", '<a id="same"></a>\n<a id="same"></a>'), "D2"),
        ):
            original = path.read_text()
            with self.subTest(check=expected):
                try:
                    support.sub(path, *replacement)
                    findings = self.findings(root)
                    self.assertIn(expected, {item["code"] for item in findings}, findings)
                    self.assertFalse({"D3", "D4"} & {item["code"] for item in findings}, findings)
                finally:
                    support.w(path, original)

    # @trace docs/ru/codes.md#d5,ADR-015
    def test_d5_allows_decisions_but_still_rejects_other_work(self):
        root = self.project()
        decision = self.decision(root, "adr-001-base.md", directory="workflow/adr")
        with (root / "docs/guide.md").open("a") as stream:
            stream.write("\n[Decision](../" + decision.relative_to(root).as_posix() + ")\n")
        self.assertFalse([item for item in self.findings(root) if item["code"] == "D5"])
        work = [support.doc(root, kind) for kind in ("pln", "iss")]
        work.append(self.decision(root, "dsc-001-compare.md", "open", directory="workflow/discussion/2026"))
        work.append(self.decision(root, "aud-001-review.md", "completed", directory="workflow/audit/2026"))
        with (root / "docs/guide.md").open("a") as stream:
            for path in work:
                stream.write("\n[Work](../" + path.relative_to(root).as_posix() + ")\n")
        findings = [item for item in self.findings(root) if item["code"] == "D5"]
        self.assertEqual({item["subject"] for item in findings},
                         {"../" + path.relative_to(root).as_posix() for path in work})

    # @trace docs/ru/codes.md#t3,ADR-015
    def test_ordinary_links_report_status_with_levels_but_historical_work_links_do_not(self):
        root = self.configured()
        for source, link in (("docs/guide.md", "adr/0001-base.md"),
                             ("AGENTS.md", "docs/adr/0001-base.md"),
                             (".agents/local.md", "../docs/adr/0001-base.md")):
            path = root / source
            old = path.read_text() if path.exists() else "# Local rules\n"
            support.w(path, old + '\n## Prior <a id="prior"></a>\n\n[Prior decision](' + link + ")\n")
        plan = support.doc(root, "pln")
        support.w(plan, plan.read_text() + "\n[Historical](../../../docs/adr/0001-base.md)\n")
        for status in ("superseded", "rejected"):
            self.decision(root, status=status)
            for level in ("warning", "error", "off"):
                with self.subTest(status=status, level=level):
                    support.set_config(root, codes={"T3": level})
                    code, result = support.check_json(root)
                    self.assertEqual(code, 1 if level == "error" else 0, result)
                    matches = [item for item in result["warnings"] + result["errors"]
                               if item["code"] == "T3"]
                    expected = {"docs/guide.md", "AGENTS.md", ".agents/local.md"}
                    self.assertEqual({item["file"] for item in matches}, expected if level != "off" else set())
                    self.assertEqual(len(matches), 0 if level == "off" else len(expected))
                    for item in matches:
                        self.assertEqual(item["subject"], "ADR-001 " + status)
                        self.assertIn('link', item["message"].lower())
                        self.assertIn('Check whether the text is still current', item["message"])
                        self.assertNotIn('check the code', item["message"])
                    for source in sorted(expected):
                        sliced = self.slice(root, source + "#prior")
                        signals = [item for item in self.items(sliced, "signals") if item["code"] == "T3"]
                        self.assertEqual(len(signals), 0 if level == "off" else 1, sliced)
                        for signal in signals:
                            self.assertEqual((signal["target"], signal["level"], signal["path"]),
                                             ("ADR-001", level, source))
                            self.assertIn('Check whether the text is still current', signal["message"])

    # @trace docs/ru/codes.md#w3,ADR-015
    def test_refinement_header_is_repeatable_and_only_accepted_relations_oblige(self):
        root = self.configured()
        self.decision(root)
        self.decision(root, "0002-child.md", header=
                      "- Refines: [ADR-1](0001-base.md)\n- Refines: [ADR-0003](0003-other.md)\n")
        self.decision(root, "0003-other.md")
        for number, status in ((4, "rejected"), (5, "proposed"), (6, "superseded")):
            self.decision(root, "%04d-inactive.md" % number, status,
                          header="- Refines: [Base](0001-base.md)\n")
        self.decision(root, "0007-context.md", body="\n[Base](0001-base.md)\n")
        self.decision(root, "0008-body.md", body="\n- Refines: [Base](0001-base.md)\n")
        self.decision(root, "0009-on-rejected.md", header="- Refines: [Old](0004-inactive.md)\n")
        self.decision(root, "0010-text.md", header="- Refines: ADR-001\n")
        support.w(root / "docs/covers.md", '# Coverage <a id="coverage"></a>\n\n<!-- covers: ADR-0001 -->\n')
        support.w(root / "docs/direct.md", '# Direct <a id="direct"></a>\n\nRule.\n')
        self.decision(root, "0011-linked.md", body="\n[Direct](../direct.md#direct)\n")
        self.decision(root, "0012-child.md", header="- Refines: [Linked](0011-linked.md)\n")
        support.w(root / "src/order.py", "# %s docs/guide.md#max-discount, ADR-0001\nvalue = 1\n" % support.TAG)
        self.assertFalse([item for item in self.findings(root) if item["code"] in ("T1", "D6")])
        expected = {
            "ADR-1": {"ADR-001", "ADR-002"},
            "ADR-2": {"ADR-001", "ADR-002", "ADR-003"},
            "ADR-4": set(),
            "ADR-5": set(),
            "ADR-6": set(),
            "docs/guide.md#max-discount": {"ADR-001", "ADR-002"},
            "src/order.py": {"ADR-001", "ADR-002"},
            "docs/covers.md#coverage": {"ADR-001", "ADR-002"},
            "docs/direct.md#direct": {"ADR-011", "ADR-012"},
            "ADR-7": {"ADR-007"},
            "ADR-8": {"ADR-008"},
            "ADR-9": {"ADR-009"},
            "ADR-10": {"ADR-010"},
        }
        for query, obey in expected.items():
            with self.subTest(target=query):
                result = self.slice(root, query)
                self.assertEqual({item["target"] for item in self.items(result, "obey")}, obey)
                if query in ("ADR-7", "ADR-8"):
                    self.assertIn("ADR-001", {item["target"] for item in self.items(result, "context")})
                if query == "ADR-9":
                    self.assertIn(("ADR-004", "T3"), {(item["target"], item["code"])
                                                     for item in self.items(result, "signals")})

    def test_refinement_chains_do_not_add_siblings_and_cycles_stay_finite(self):
        root = self.configured()
        base = self.decision(root)
        self.decision(root, "0002-child.md", header="- Refines: [Base](0001-base.md)\n")
        sibling = self.decision(root, "0003-sibling.md", header="- Refines: [Base](0001-base.md)\n")
        self.decision(root, "0004-grandchild.md", header="- Refines: [Child](0002-child.md)\n")
        result = self.slice(root, "ADR-2")
        self.assertEqual({item["target"] for item in self.items(result, "obey")},
                         {"ADR-001", "ADR-002", "ADR-004"})
        sibling.unlink()
        support.sub(base, "- Status: accepted\n", "- Status: accepted\n- Refines: [Child](0002-child.md)\n")
        support.w(root / "src/order.py", "# %s ADR-1\nvalue = 1\n" % support.TAG)
        for query in ("ADR-1", "ADR-2"):
            with self.subTest(target=query):
                first, second = self.slice(root, query), self.slice(root, query)
                self.assertEqual(first, second)
                obey = self.items(first, "obey")
                self.assertEqual({item["target"] for item in obey}, {"ADR-001", "ADR-002", "ADR-004"})
                self.assertEqual(len(obey), 3)
                paths = [(item["path"], item["line"]) for item in self.items(first, "code")]
                self.assertEqual(len(paths), len(set(paths)))
