"""Explicit repository settings and C1 boundaries."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))
from lipi.checker.config import load_config, validate_config, validate_settings


class RepositorySettings(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lipi-repos-config-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = self.directory / "project"
        self.root.mkdir()

    @staticmethod
    def connection(path="../neighbor", read=None):
        return {"path": path, "read": ["docs"] if read is None else read}

    def errors(self, repos, **options):
        return validate_settings(self.root, {"repos": repos}, **options)

    def test_absent_and_empty_repos_keep_single_project_defaults(self):
        original = load_config(self.root, None)
        self.assertNotIn("repos", original)
        self.assertEqual(validate_config(self.root, original), [])
        support.w(self.root / "lipi.json", '{"repos": {}}')
        configured = load_config(self.root, None)
        self.assertEqual(configured.pop("repos"), {})
        self.assertEqual(configured, original)
        self.assertEqual(self.errors({}), [])

    def test_aliases_and_capabilities(self):
        repos = {name: self.connection("../" + name, list(read))
                 for name, read in (("core", ["docs"]), ("core-2", ["decisions"]),
                                    ("2", ["code", "tests"]),
                                    ("-", ["docs", "decisions", "code", "tests"]))}
        self.assertEqual(self.errors(repos), [])

    def test_layer_separator_is_reserved_only_with_connections(self):
        cfg = {"layers": {"src/*": "client::ui"}}
        self.assertEqual(validate_settings(self.root, cfg), [])
        self.assertEqual(validate_settings(self.root, dict(cfg, repos={})), [])
        cfg["repos"] = {"client": self.connection()}
        errors = validate_settings(self.root, cfg)
        self.assertEqual(len(errors), 1)
        self.assertIn(support.localized('layer names cannot contain "::"', 'имя слоя не содержит «::»'), errors[0][1])

    def test_invalid_mapping_and_aliases(self):
        for repos in (None, [], "core", 1, True):
            with self.subTest(repos=repos):
                self.assertTrue(self.errors(repos))
        for alias in ("", "Core", "with_space", "with space", "сосед", "a/b", "a::b", "a\n"):
            with self.subTest(alias=alias):
                self.assertTrue(self.errors({alias: self.connection()}))

    def test_connection_requires_exact_path_and_read_fields(self):
        for item in (None, [], "../neighbor", 1, {}, {"path": "../neighbor"},
                     {"read": ["docs"]}, dict(self.connection(), extra=True)):
            with self.subTest(item=item):
                errors = self.errors({"core": item})
                self.assertTrue(errors)
                self.assertIn("core", errors[0][1])

    def test_invalid_paths(self):
        for path in (None, False, 1, [], {}, "", "  ", "/absolute", "../nul\0path"):
            with self.subTest(path=path):
                errors = self.errors({"core": self.connection(path)})
                self.assertTrue(errors)
                self.assertIn("path", errors[0][1])

    def test_invalid_read(self):
        for read in (None, True, 1, "docs", {}, [], [1], [None], [[]],
                     [""], ["Docs"], ["workflow"], ["docs", "docs"]):
            with self.subTest(read=read):
                errors = self.errors({"core": {"path": "../neighbor", "read": read}})
                self.assertTrue(errors)
                self.assertIn(support.localized('"core": "read":', '«core»: «read»:'), errors[0][1])

    def test_missing_directory_and_regular_file_are_not_c1(self):
        support.w(self.directory / "neighbor-file", "content")
        for path in ("../missing", "nested/missing", "../neighbor-file", "../neighbor-file/child"):
            with self.subTest(path=path):
                self.assertEqual(self.errors({"core": self.connection(path)}), [])

    def test_self_connection_including_symlinks_is_c1(self):
        (self.root / "self-link").symlink_to(self.root, target_is_directory=True)
        paths = [".", "../project", "self-link", "nested/.."]
        if (self.directory / "PROJECT").exists():
            paths.append("../PROJECT")
        for path in paths:
            with self.subTest(path=path):
                errors = self.errors({"core": self.connection(path)})
                self.assertTrue(errors)
                self.assertIn(support.localized('connects to the project itself', 'самому проекту'), errors[0][1])

    def test_duplicate_physical_roots_including_symlinks_are_c1(self):
        neighbor = self.directory / "neighbor"
        neighbor.mkdir()
        (self.root / "neighbor-link").symlink_to(neighbor, target_is_directory=True)
        paths = ["../neighbor", "../neighbor/.", "neighbor-link"]
        if (self.directory / "NEIGHBOR").exists():
            paths.append("../NEIGHBOR")
        for path in paths:
            with self.subTest(path=path):
                errors = self.errors({"core": self.connection(), "alias": self.connection(path)})
                self.assertEqual(len(errors), 1)
                self.assertIn(support.localized('have the same root', 'один корень'), errors[0][1])
        self.assertTrue(self.errors({"core": self.connection("../missing"),
                                     "alias": self.connection("../missing/.")}))

    def test_symbolic_project_root_is_compared_physically(self):
        root_link = self.directory / "project-link"
        root_link.symlink_to(self.root, target_is_directory=True)
        errors = validate_settings(root_link, {"repos": {"core": self.connection("../project")}})
        self.assertTrue(errors)
        self.assertIn(support.localized('connects to the project itself', 'самому проекту'), errors[0][1])

    def test_symlink_loop_is_c1_without_traceback(self):
        (self.root / "loop").symlink_to("loop")
        support.w(self.root / "lipi.json", json.dumps({"repos": {"core": self.connection("loop")}}))
        self.assertTrue(self.errors({"core": self.connection("loop")}))
        code, output = support.check(self.root)
        self.assertEqual(code, 2, output)
        self.assertTrue(support.found(output, "C1"), output)
        self.assertNotIn("Traceback", output)

    def test_neighbor_validation_does_not_resolve_its_connections(self):
        (self.root / "loop").symlink_to("loop")
        repos = {"core": self.connection("loop"), "self": self.connection(".")}
        with patch.object(Path, "resolve", side_effect=AssertionError("third root was resolved")):
            self.assertEqual(self.errors(repos, repo_roots=False), [])
            self.assertTrue(self.errors({"core": {"path": "loop"}}, repo_roots=False))

    def test_settings_validation_skips_lock_and_baseline(self):
        support.w(self.root / support.LOCK_REL, "invalid JSON")
        support.w(self.root / support.BASE_REL, "invalid JSON")
        with patch("lipi.checker.config._read_json", side_effect=AssertionError("state was read")):
            self.assertEqual(validate_settings(self.root, {}), [])
        self.assertEqual({path for path, _ in validate_config(self.root, {})},
                         {support.LOCK_REL, support.BASE_REL})

    def test_neighbor_settings_still_validate_decisions_boundary(self):
        neighbor = self.directory / "neighbor"
        neighbor.mkdir()
        (self.root / "decisions").symlink_to(neighbor, target_is_directory=True)
        errors = validate_settings(self.root, {"decisions": "decisions"}, repo_roots=False)
        self.assertTrue(errors)
        self.assertIn("decisions", errors[0][1])


class RepositorySettingsCLI(support.Case):
    def test_schema_errors_return_c1_and_exit_two_before_other_checks(self):
        root = self.project()
        support.w(root / "docs/broken.md", "# Broken\n\n[Missing](missing.md)\n")
        for repos in ([], {"Core": {"path": "../neighbor", "read": ["docs"]}},
                      {"core": {"path": ".", "read": ["docs"]}},
                      {"core": {"path": "../neighbor", "read": []}}):
            with self.subTest(repos=repos):
                support.set_config(root, repos=repos)
                code, data = support.check_json(root)
                self.assertEqual(code, 2, data)
                self.assertEqual({item["code"] for item in data["errors"]}, {"C1"})
                self.assertEqual(data["warnings"], [])

    def test_empty_repos_leave_existing_check_slice_and_map_output_unchanged(self):
        root = self.project()
        commands = (("check", "--format", "json"),
                    ("slice", "docs/guide.md#max-discount", "--format", "json"),
                    ("map", "--format", "json"))
        before = [support.cli(root, *command) for command in commands]
        support.set_config(root, repos={})
        after = [support.cli(root, *command) for command in commands]
        self.assertEqual(before, after)
