"""Release checks exercised on both Windows Python versions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests import support
from lipi.i18n import tr


class PortableProject(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lipi-portable-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()

    def check(self, root):
        code, out = support.check(root, "--format", "json", env={"CI": "true"})
        result = json.loads(out)
        return code, [(item["code"], item["file"]) for item in result["errors"] + result["warnings"]]

    # @trace docs/ru/workflow.md#ownership,docs/ru/codes.md#v3
    def test_clean_git_checkouts_and_windows_lock(self):
        support.git_init(self.root)
        support.w(self.root / ".gitattributes", "* text=auto\n")
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)
        lock = json.loads((self.root / support.LOCK_REL).read_bytes())
        self.assertIn(support.CI_REL, lock["files"])
        for name, digest in lock["files"].items():
            lf = (self.root / name).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(digest, hashlib.sha256(lf).hexdigest(), name)
        self.assertEqual(support.commit(self.root)[0], 0)

        for autocrlf in ("false", "true"):
            with self.subTest(autocrlf=autocrlf):
                clone = self.base / autocrlf
                code, out = support.git(self.base, "clone", "-q", "--no-local", "-c",
                                        "core.autocrlf=" + autocrlf, "-c", "core.eol=lf",
                                        str(self.root), str(clone))
                self.assertEqual(code, 0, out)
                index = clone / "workflow/INDEX.md"
                self.assertEqual(b"\r\n" in index.read_bytes(), autocrlf == "true")
                self.assertEqual(self.check(clone), (0, []))
                managed = {clone / name for name in lock["files"]}
                watched = managed | set((clone / "workflow/index").rglob("*.md")) | {index}
                before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}
                self.assert_no_init_changes(clone)
                self.assertEqual(support.git(clone, "status", "--porcelain"), (0, ""))

                # 1.4.2 on Windows recorded the hash of each rendered CRLF template.
                old = json.loads((clone / support.LOCK_REL).read_bytes())
                old["lipi"] = "1.4.2"
                for name in old["files"]:
                    lf = (clone / name).read_bytes().replace(b"\r\n", b"\n")
                    old["files"][name] = hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()
                support.w(clone / support.LOCK_REL, json.dumps(old, sort_keys=True, indent=2) + "\n")
                self.assertEqual(self.check(clone), (0, []))
                old_lock_bytes = (clone / support.LOCK_REL).read_bytes()
                code, out = support.cli(clone, "ci", "github")
                self.assertEqual(code, 0, out)
                self.assertEqual((clone / support.LOCK_REL).read_bytes(), old_lock_bytes)
                code, out = support.init(clone)
                self.assertEqual(code, 0, out)
                self.assert_no_init_changes(clone)
                upgraded = json.loads((clone / support.LOCK_REL).read_bytes())
                self.assertEqual(upgraded, lock)
                self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}, before)

                rule = ".agents/lipi/README.md"
                with (clone / rule).open("ab") as stream:
                    stream.write(b"changed rule\r\n")
                self.assertEqual(self.check(clone), (1, [("V3", rule)]))
                index.write_bytes(b"# User index\r\n")
                code, out = support.cli(clone, "index")
                self.assertNotEqual(code, 0, out)
                self.assertEqual(index.read_bytes(), b"# User index\r\n")
                self.assertIn(("W7", "workflow/INDEX.md"), self.check(clone)[1])

    def assert_no_init_changes(self, root):
        code, out = support.init(root, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertNotIn(tr("init.change_plan").split("%s")[0].strip(), out)

    # @trace docs/ru/settings.md#repos
    def test_repository_paths_are_project_relative(self):
        for root in (self.root, self.base / "neighbor"):
            support.w(root / "lipi.json", '{"workflow":null}')
            support.w(root / "docs/README.md", '# Guide <a id="guide"></a>\n')
        support.w(self.root / "docs/README.md", "# Local project\n")
        for path in ("/absolute", r"\rooted", "C:/other", r"C:\other", "C:other", r"\\server\share"):
            with self.subTest(path=path):
                support.set_config(self.root, repos={"lib": {"path": path, "read": ["docs"]}})
                code, out = support.check(self.root, "--format", "json")
                self.assertEqual(code, 2, out)
                self.assertEqual([e["code"] for e in json.loads(out)["errors"]], ["C1"])
        support.set_config(self.root, repos={"lib": {"path": "../neighbor", "read": ["docs"]}})
        self.assertEqual(self.check(self.root), (0, []))
        code, out = support.cli(self.root, "slice", "lib::docs/README.md#guide", "--format", "json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["target"]["target"], "docs/README.md#guide")
