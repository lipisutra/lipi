"""Real CLI cost with history, reverse consumers and dirty metadata."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support, test_slice


class RepositoryPerformance(unittest.TestCase):
    # @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
    def test_thousand_places_three_repositories_with_history_and_untracked_files(self):
        fixture = test_slice.SliceContract()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.profile_project()
        workspace = tempfile.TemporaryDirectory(prefix="lipi-repos-profile-")
        self.addCleanup(workspace.cleanup)
        base = Path(workspace.name)
        roots = [base / name for name in ("project", "core", "client")]
        for part, root in enumerate(roots):
            shutil.copytree(fixture.root, root)
            for path in (root / "src").glob("module_*.py"):
                number = int(path.stem.split("_")[1])
                if number % 3 != part:
                    path.unlink()
                elif part:
                    text = path.read_text().replace(
                        support.TAG + " " + test_slice.TARGET,
                        support.TAG + " engine::" + test_slice.TARGET)
                    support.w(path, text)
            repos = ({"core": {"path": "../core", "read": ["code", "tests"]},
                      "client": {"path": "../client", "read": ["code", "tests"]}}
                     if part == 0 else
                     {"engine": {"path": "../project", "read": ["docs"]},
                      "unused": {"path": "../not-connected", "read": ["code"]}})
            support.set_config(root, repos=repos, skip_dirs=["scratch"],
                               layers={"src/*": ("api", "domain", "ui")[part]})
            if part:
                # Tracked directories force status to inspect their untracked entries;
                # code traversal excludes them, so this exercises metadata cost itself.
                for folder in range(100):
                    support.w(root / ("scratch/%03d/keep.txt" % folder), "tracked\n")
            code, out = support.commit(root, "partition synthetic repository",
                                       date="2026-11-13T12:00:00+00:00")
            self.assertEqual(code, 0, out)
            code, out = support.git(root, "rev-list", "--count", "HEAD")
            self.assertEqual((code, int(out)), (0, 41))
            if part:
                for number in range(3000):
                    support.w(root / ("scratch/%03d/untracked_%04d.txt" % (number % 100, number)),
                              "untracked\n")
        with support.time_budget(self, "slice: three repositories with untracked files"):
            code, output = support.cli(roots[0], "slice", test_slice.TARGET, "--format", "json")
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual(result["summary"]["code"], 1000)
        self.assertEqual(result["summary"]["repos"], 3)
        metadata = result["checks"]["repos"]
        self.assertEqual([item["repo"] for item in metadata], [None, "core", "client"])
        self.assertEqual([item["dirty"] for item in metadata], [False, True, True])
        self.assertTrue(all(item["state"] == "ok" and item["head"] for item in metadata))
        self.assertFalse(result["reproducible"])
        self.assertEqual(result["checks"]["staleness"]["total"], 334)
        with support.time_budget(self, "map: three repositories with untracked files"):
            code, output = support.cli(roots[0], "map", "--format", "json")
        self.assertEqual(code, 0, output)
        mapped = json.loads(output)
        row = next(item for item in mapped["rows"] if item["target"] == test_slice.TARGET)
        self.assertEqual(sum(row["code"].values()), 1000)
        self.assertEqual([item["dirty"] for item in mapped["checks"]["repos"]],
                         [False, True, True])
