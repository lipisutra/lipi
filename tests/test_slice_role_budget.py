"""CLI acceptance for role counts and slice output limits."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests import support


TARGET = "docs/export.md#row"
LAST_PARAGRAPH = "Keep the escape character."
ENTRY = "src/api.py:1"
READER = "src/reader.py:1"
FALLBACK = "src/reader.py:5"
VERIFY = "ops/verify.py:1"


# @trace docs/ru/slice-output.md#roles,docs/ru/slice.md#budget
class SliceRoleBudget(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lipi-slice-role-budget-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = self.tmp / "project"
        support.w(self.root / "lipi.json", "{}\n")
        support.set_config(self.root, layers={"src/*": "export", "ops/*": "inspection"},
                           entry=["^def open_export"])
        support.w(self.root / "docs/export.md",
                  '# Export\n\n## Row <a id="row"></a>\n\nRead the row.\n\n'
                  + LAST_PARAGRAPH + "\n")
        for path, declarations in (
            ("src/api.py", [("open_export", "")]),
            ("src/reader.py", [("read_export", " role=consumes"), ("fallback", "")]),
            ("ops/verify.py", [("verify", "")]),
            ("src/writer.py", [("write_export", " role=produces")]),
        ):
            source = "\n".join(
                f"# {support.TAG} {TARGET}{role}\ndef {symbol}():\n    return 0\n"
                for symbol, role in declarations
            )
            support.w(self.root / path, source)
        support.git_init(self.root)
        code, out = support.commit(self.root)
        self.assertEqual(code, 0, out)

    def run_slice(self, env, *args):
        code, out = support.run(
            support.PY + [str(support.CLI), "slice", TARGET, "--role", "consumes", *args],
            cwd=self.root, env=env,
        )
        self.assertEqual(code, 0, out)
        return out

    def test_role_totals_precede_display_limits(self):
        for language, entry_summary, code_label, consumer, extra, staleness, entry_heading, shown in (
            ("en", "1 entry point", "code locations", "1 consumer",
             "%d more locations without a role", "checked 5 of 5 locations for staleness",
             "Entry points", "showing %d of %d"),
            ("ru", "1 точка входа", "места в коде", "1 потребитель",
             "ещё %d места без роли", "устаревание проверено для 5 из 5 мест",
             "С чего начинать", "показано %d из %d"),
        ):
            env = support.language_env(self.tmp / language, language)
            for budget, args, layered_code, visible_code in (
                (60, (), 3, (READER, FALLBACK, VERIFY)),
                (60, ("--only", "code"), 3, (READER, FALLBACK, VERIFY)),
                (60, ("--layer", "export"), 2, (READER, FALLBACK)),
                (3, (), 3, (READER,)),
                (3, ("--full",), 3, (READER, FALLBACK)),
            ):
                with self.subTest(language=language, budget=budget, args=args):
                    support.set_config(self.root, slice_budget=budget)
                    result = json.loads(self.run_slice(env, *args, "--format", "json"))
                    output = self.run_slice(env, *args)
                    summary = result["summary"]
                    self.assertEqual((summary["entry"], summary["code"]), (1, layered_code + 1))
                    self.assertEqual(summary["roles"], {
                        "role": "consumes", "matched": 1, "unassigned": layered_code, "unrecognized": 0,
                    })
                    self.assertEqual(result["checks"]["staleness"], {
                        "state": "full", "checked": 5, "total": 5,
                    })
                    self.assertIn(staleness, output.splitlines())
                    summary_line = output.splitlines()[1]
                    for part in (entry_summary, consumer, extra % layered_code):
                        self.assertIn(part, summary_line)
                    self.assertEqual(re.findall(rf"(\d+) {code_label}", summary_line),
                                     [str(summary["code"])], output)

                    blocks = {block["kind"]: block for block in result["blocks"]}
                    code_block = blocks["code"]
                    only_code = "--only" in args
                    self.assertEqual("entry" in blocks, not only_code)
                    self.assertEqual(entry_heading in output.splitlines(), not only_code)
                    expected = {"code": visible_code}
                    if not only_code:
                        expected["entry"] = (ENTRY,)
                    for kind, addresses in expected.items():
                        self.assertEqual(tuple(f'{item["path"]}:{item["line"]}'
                                               for item in blocks[kind]["items"]), addresses)
                    visible_entry = () if only_code else (ENTRY,)
                    self.assertEqual(tuple(re.findall(r"^  ((?:src|ops)/\S+:\d+)  ", output, re.M)),
                                     visible_entry + visible_code)

                    omitted = layered_code - len(visible_code)
                    self.assertEqual(code_block["omitted"], omitted)
                    omission_lines = [line for line in output.splitlines() if "--only code" in line]
                    self.assertEqual(len(omission_lines), int(bool(omitted)), output)
                    if omitted:
                        self.assertIn(shown % (len(visible_code), layered_code), omission_lines[0])
                    self.assertEqual(result["incomplete"], budget == 3)

                    full_excerpt = not only_code and (budget == 60 or "--full" in args)
                    excerpt = blocks.get("excerpt", {}).get("items", [])
                    self.assertEqual(any(LAST_PARAGRAPH in item["text"] for item in excerpt),
                                     full_excerpt)
                    self.assertEqual(LAST_PARAGRAPH in output, full_excerpt)
