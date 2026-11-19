"""История областей: сравнение с настоящим whole-file git blame -w -M -C."""
import datetime
from contextlib import contextmanager, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support

sys.path.insert(0, str(support.LIPI / "src"))
from lipi.checker.history import GitBlame


@contextmanager
def advancing_blame_clock(start):
    """Real Git history, with deterministic per-call dates for dirty rows."""
    real_run = subprocess.run
    calls = []
    with patch("lipi.checker.history.time.time", return_value=start) as clock:
        def run(args, **kwargs):
            result = real_run(args, **kwargs)
            if "blame" in args:
                calls.append(args)
                clock.return_value += 2
                dirty, rows = False, []
                for line in result.stdout.decode("utf-8").splitlines():
                    fields = line.split()
                    if fields and len(fields[0]) in (40, 64) and len(fields) in (3, 4):
                        dirty = set(fields[0]) == {"0"}
                    if dirty and line.startswith("committer-time "):
                        line = "committer-time %d" % clock.return_value
                    rows.append(line)
                result.stdout = ("\n".join(rows) + "\n").encode("utf-8")
            return result

        with patch("lipi.checker.history.subprocess.run", side_effect=run):
            yield clock, calls


def blame_rows(root, path, *options):
    """Независимый oracle: не вызывает парсер или кэши GitBlame."""
    output = subprocess.check_output(
        ["git", "-C", str(root), "blame", "-w", "-M", *options,
         "--line-porcelain", "--", path], stderr=subprocess.DEVNULL,
        text=True)
    result, timestamp = [], None
    for line in output.splitlines():
        if line.startswith("committer-time "):
            timestamp = int(line.split()[1])
        elif line.startswith("\t"):
            result.append((timestamp, line[1:]))
    return result


class WholeFileBlame:
    """Прежний алгоритм для сравнения полного ответа slice, без оптимизаций."""

    def __init__(self, root, *, uncommitted_time=None):
        self.root, self.cache = root, {}

    def lines(self, path):
        if path not in self.cache:
            try:
                self.cache[path] = blame_rows(self.root, path, "-C")
            except (OSError, ValueError, subprocess.CalledProcessError):
                self.cache[path] = None
        return self.cache[path]

    def region_time(self, path, start, starts, *, code=False):
        from lipi.checker.conventions import RE_TRACE

        rows = self.lines(path)
        if not rows:
            return None
        end = min((line - 1 for line in starts if line > start), default=len(rows))
        begin = start - 1
        if code and begin < len(rows):
            remainder = "".join(RE_TRACE.sub("", rows[begin][1]).split())
            if remainder in ("", "#", "//", "--", ";", "*", "/**/", "<!---->"):
                begin += 1
        return max((timestamp for timestamp, _ in rows[begin:end]
                    if timestamp is not None), default=0) or None

    def lines_time(self, path, line_numbers):
        rows = self.lines(path)
        if rows is None:
            return None
        selected = set(line_numbers)
        return max((timestamp for number, (timestamp, _) in enumerate(rows, 1)
                    if number in selected and timestamp is not None), default=0) or None

    def stale_region_time(self, path, start, starts, *, since, code=True):
        timestamp = self.region_time(path, start, starts, code=code)
        return timestamp if timestamp is not None and timestamp > since else None

    def region_checked(self, path, start, starts, *, since, code=True):
        return self.lines(path) is not None

    def preload_staleness(self, requests, workers=8, *, max_cheap_files=None, max_precise_files=None):
        paths = {path for path, _, _, _ in requests}
        if paths:
            with ThreadPoolExecutor(max_workers=min(workers, len(paths))) as pool:
                list(pool.map(self.lines, paths))


def oracle_slice(root, target):
    """Тот же публичный JSON-ответ, но вся история вычислена прежним blame."""
    from lipi.checker.config import load_config
    from lipi.checker.model import Project
    from lipi.i18n import use_language
    from lipi.slice_output import select_response
    from lipi.slice_query import build_slice

    root = Path(root).resolve()
    cfg = load_config(root, None)
    with use_language("en"), patch("lipi.slice_query.GitBlame", WholeFileBlame):
        response, code = build_slice(Project(root, cfg), target)
    if code:
        raise AssertionError((code, response))
    return select_response(response, cfg["slice_budget"], False, None)


class GitBlameEquivalence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lipi-history-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        support.git_init(self.root)

    def write(self, path, text):
        support.w(self.root / path, text)

    def commit(self, day):
        code, output = support.commit(self.root, date="2026-01-%02dT00:00:00+00:00" % day)
        self.assertEqual(code, 0, output)

    @staticmethod
    def timestamp(day):
        return int(datetime.datetime(2026, 1, day, tzinfo=datetime.timezone.utc).timestamp())

    def move_chunk(self, original_day=1, move_day=3):
        # Each line has fewer than -C's default 40 alphanumeric characters;
        # the whole copied block has enough. Both files survive the move.
        chunk = "".join("    value_%d = %d\n" % (i, i) for i in range(10))
        self.write("source.py", "def source():\n" + chunk + "    return 0\n")
        self.write("target.py", "# unique target placeholder\n")
        self.commit(original_day)
        self.write("source.py", "def source():\n    return 0\n")
        self.write("target.py", "# unique target placeholder\n" + chunk)
        self.commit(move_day)

    def test_single_line_copy_needs_context_outside_region(self):
        self.move_chunk()
        full = blame_rows(self.root, "target.py", "-C")
        isolated = blame_rows(self.root, "target.py", "-C", "-L", "2,2")
        self.assertEqual(full[1][0], self.timestamp(1))
        self.assertEqual(isolated[0][0], self.timestamp(3))
        history = GitBlame(self.root)
        self.assertIsNone(history.stale_region_time(
            "target.py", 2, [2, 3], since=self.timestamp(2), code=False))
        self.assertEqual(history.region_time("target.py", 2, [2, 3]), full[1][0])

    def test_nonmonotonic_commit_dates_do_not_hide_stale_copy(self):
        self.move_chunk(original_day=3, move_day=1)
        cheap = blame_rows(self.root, "target.py")
        full = blame_rows(self.root, "target.py", "-C")
        self.assertLess(cheap[1][0], self.timestamp(2))
        self.assertGreater(full[1][0], self.timestamp(2))
        history = GitBlame(self.root)
        history.preload_staleness([("target.py", 2, [2], self.timestamp(2))])
        self.assertEqual(history.stale_region_time(
            "target.py", 2, [2], since=self.timestamp(2), code=False), full[1][0])

    def test_regions_with_different_document_dates_keep_full_blame_results(self):
        tag = "# %s docs/guide.md#" % support.TAG
        original = (tag + "untouched\nstable = 1\n" + tag + "semantic\nchanged = 1\n"
                    + "inline = 1  " + tag + "inline\n" + tag + "standalone\nkept = 1\n")
        moved = "".join("moved_value_%d = %d\n" % (i, i) for i in range(10))
        self.write("target.py", original)
        self.write("source.py", moved + "source_remains = True\n")
        self.commit(1)
        revised = original.replace("changed = 1", "changed = 2").replace("inline = 1", "inline = 2")
        revised = revised.replace(tag + "standalone", tag + "renamed")
        self.write("target.py", revised + tag + "moved\n" + moved)
        self.write("source.py", "source_remains = True\n")
        self.commit(3)
        starts = [1, 3, 5, 6, 8]
        raw = blame_rows(self.root, "target.py", "-C")
        # Explicit body ranges independently encode standalone versus inline markers.
        expected = {1: raw[1][0], 3: raw[3][0], 5: raw[4][0], 6: raw[6][0],
                    8: max(timestamp for timestamp, _ in raw[8:])}
        self.assertEqual(expected, {1: self.timestamp(1), 3: self.timestamp(3),
                                    5: self.timestamp(3), 6: self.timestamp(1),
                                    8: self.timestamp(1)})
        history = GitBlame(self.root)
        requests = [("target.py", start, starts, self.timestamp(day))
                    for day in (2, 4, 1) for start in starts]
        history.preload_staleness(requests)
        for path, start, boundaries, since in reversed(requests):
            with self.subTest(start=start, since=since):
                timestamp = expected[start]
                self.assertEqual(history.stale_region_time(path, start, boundaries, since=since),
                                 timestamp if timestamp > since else None)
                self.assertEqual(history.region_time(path, start, boundaries, code=True), timestamp)

    def test_exact_lines_and_missing_files_preserve_original_contract(self):
        self.move_chunk()
        history = GitBlame(self.root)
        self.assertEqual(history.lines("target.py"), blame_rows(self.root, "target.py", "-C"))
        self.assertIsNone(history.lines("missing.py"))
        self.assertIsNone(history.stale_region_time(
            "missing.py", 1, [1], since=self.timestamp(1)))

    def test_dirty_rows_share_run_time_across_files_passes_and_read_order(self):
        for path in ("guide.md", "code.py"):
            self.write(path, "first = 1\ndirty = 1\nlast = 1\n")
        self.commit(1)
        for path in ("guide.md", "code.py"):
            self.write(path, "first = 1\ndirty = 2\nlast = 1\n")
        for paths in (("guide.md", "code.py"), ("code.py", "guide.md")):
            for readers in (("cheap_lines", "lines"), ("lines", "cheap_lines")):
                with self.subTest(paths=paths, readers=readers):
                    instant = self.timestamp(4) + 0.5
                    with advancing_blame_clock(instant) as (_, calls):
                        history = GitBlame(self.root)
                        for reader in readers:
                            for path in paths:
                                self.assertEqual(getattr(history, reader)(path), [
                                    (self.timestamp(1), "first = 1"),
                                    (instant, "dirty = 2"),
                                    (self.timestamp(1), "last = 1"),
                                ])
                        self.assertEqual(history.lines_time("guide.md", (2,)), instant)
                        self.assertIsNone(history.stale_region_time(
                            "code.py", 2, [2, 3], since=instant, code=False))
                    self.assertEqual(len(calls), 4)

    def test_new_history_run_has_fresh_time_and_dirty_code_is_newer_in_same_second(self):
        self.write("code.py", "value = 1\n")
        self.commit(1)
        self.write("code.py", "value = 2\n")
        for instant in (self.timestamp(1) + 0.5, self.timestamp(4) + 0.5):
            with self.subTest(instant=instant), advancing_blame_clock(instant):
                history = GitBlame(self.root)
                self.assertEqual(history.stale_region_time(
                    "code.py", 1, [1], since=self.timestamp(1)), instant)

    def dirty_project(self):
        self.write("lipi.json", '{"workflow": null}\n')
        document = ('# Guide\n\n## Rule <a id="rule"></a>\n\nValue is one.\n\n'
                    '## Other <a id="other"></a>\n\nOther rule.\n')
        self.write("docs/guide.md", document)
        self.write("src/code.py", "# %s docs/guide.md#rule\nvalue = 1\n" % support.TAG)
        self.commit(1)
        self.write("src/code.py", "# %s docs/guide.md#rule\nvalue = 2\n" % support.TAG)
        return document

    def slice_response(self):
        from lipi.checker.config import load_config
        from lipi.checker.model import Project
        from lipi.slice_query import build_slice

        root = self.root.resolve()
        response, code = build_slice(Project(root, load_config(root, None)),
                                     "docs/guide.md#rule")
        self.assertEqual(code, 0, response)
        self.assertEqual(response["checks"]["staleness"]["checked"], 1)
        return response

    @staticmethod
    def stale_signals(response):
        return [item for block in response["blocks"] if block["kind"] == "signals"
                for item in block["items"] if item["code"] == "A4"]

    def test_audit_and_slice_compare_dirty_target_region_not_whole_document(self):
        from lipi.checker.runner import main

        document = self.dirty_project()
        for change, expected in (("target", 0), ("none", 1), ("other", 1)):
            revised = document.replace("Value is one.", "Value is two.") if change == "target" else document
            if change == "other":
                revised = document.replace("Other rule.", "Other rule changed.")
            self.write("docs/guide.md", revised)
            for command in ("audit", "slice"):
                with self.subTest(change=change, command=command):
                    with advancing_blame_clock(self.timestamp(4) + 0.5) as (_, calls):
                        if command == "audit":
                            output = io.StringIO()
                            argv = ["lipi", "--root", str(self.root), "--audit", "--format", "json"]
                            with patch.object(sys, "argv", argv), redirect_stdout(output):
                                code = main()
                            self.assertNotEqual(code, 2, output.getvalue())
                            response = json.loads(output.getvalue())
                            stale = [item for item in response["warnings"] + response["errors"]
                                     if item["code"] == "A4"]
                        else:
                            stale = self.stale_signals(self.slice_response())
                    self.assertEqual(len(stale), expected, stale)
                    self.assertEqual({args[-1] for args in calls}, {"docs/guide.md", "src/code.py"})

    def test_repo_slice_retry_keeps_run_time_but_next_run_refreshes_it(self):
        from lipi.slice_query import _build_slice

        self.dirty_project()
        neighbor_tmp = tempfile.TemporaryDirectory(prefix="lipi-history-neighbor-")
        self.addCleanup(neighbor_tmp.cleanup)
        neighbor = Path(neighbor_tmp.name)
        support.w(neighbor / "lipi.json", '{"workflow": null}\n')
        support.w(neighbor / "docs/guide.md", "# Neighbor\n\nA separate rule.\n")
        support.set_config(self.root, repos={"neighbor": {
            "path": "../" + neighbor.name, "read": ["docs"]}})
        attempts = []
        with advancing_blame_clock(self.timestamp(4) + 0.5) as (clock, _):
            def lose_neighbor(index, *args, **kwargs):
                result = _build_slice(index, *args, **kwargs)
                attempts.append([dict(item) for item in self.stale_signals(result[0])])
                if len(attempts) == 1:
                    index.sources.get("neighbor").mark_unavailable("synthetic read failure")
                    clock.return_value += 120
                return result

            with patch("lipi.slice_query._build_slice", side_effect=lose_neighbor):
                response = self.slice_response()
            self.assertEqual(len(attempts), 2)
            self.assertEqual(len(attempts[0]), 1)
            self.assertEqual(attempts[0], attempts[1])
            self.assertEqual(response["checks"]["staleness"]["scope"], "local")
            self.assertTrue(response["incomplete"])
            following = self.stale_signals(self.slice_response())
            self.assertEqual(len(following), 1)
            self.assertNotEqual(attempts[0][0]["message"], following[0]["message"])

    def test_sparse_document_lines_exclude_intervening_rows_and_share_blame(self):
        original = "| Key | Meaning |\n| --- | --- |\n| Neighbor | Old |\n| Own | Stable |\n"
        self.write("guide.md", original)
        self.commit(1)
        self.write("guide.md", original.replace("Neighbor | Old", "Neighbor | New"))
        self.commit(3)
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            for lines, day in (((1, 4), 1), ((3,), 3), ((1, 3, 4), 3), ((4, 1), 1)):
                with self.subTest(lines=lines):
                    self.assertEqual(history.lines_time("guide.md", lines), self.timestamp(day))
            self.assertIsNone(history.lines_time("guide.md", ()))
        blame = [call.args[0] for call in commands.call_args_list if "blame" in call.args[0]]
        self.assertEqual(len(blame), 1, blame)
        self.assertIsNone(history.lines_time("missing.md", (1,)))

    def test_untouched_code_needs_no_blame_after_preload(self):
        self.write("code.py", "first_value = 1\nsecond_value = 2\n")
        self.commit(1)
        self.write("guide.md", "Updated documentation.\n")
        self.commit(2)
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            requests = [("code.py", start, [1, 2], self.timestamp(2)) for start in (1, 2)]
            history.preload_staleness(requests)
            for _ in range(2):
                for path, start, starts, since in requests:
                    self.assertIsNone(history.stale_region_time(
                        path, start, starts, since=since, code=False))
        blame = [call.args[0] for call in commands.call_args_list
                 if "blame" in call.args[0] and call.args[0][-1] == "code.py"]
        self.assertEqual(blame, [])

    def test_direct_current_region_shares_cheap_blame(self):
        self.write("code.py", "first_value = 1\nsecond_value = 2\n")
        self.commit(1)
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            for start in (1, 2, 1):
                self.assertIsNone(history.stale_region_time(
                    "code.py", start, [1, 2], since=self.timestamp(2), code=False))
        blame = [call.args[0] for call in commands.call_args_list if "blame" in call.args[0]]
        self.assertEqual(len(blame), 1, blame)
        self.assertNotIn("-C", blame[0][blame[0].index("blame") + 1:])

    def test_lower_cutoff_after_preload_does_not_reuse_stronger_bound(self):
        self.write("code.py", "value = 1\n")
        self.commit(1)
        self.write("code.py", "value = 3\n")
        self.commit(3)
        expected = blame_rows(self.root, "code.py", "-C")[0][0]
        history = GitBlame(self.root)
        history.preload_staleness([("code.py", 1, [1], self.timestamp(4))])
        self.assertIsNone(history.stale_region_time("code.py", 1, [1], since=self.timestamp(4)))
        self.assertEqual(history.stale_region_time("code.py", 1, [1], since=self.timestamp(2)), expected)

    def test_recent_semantic_change_still_uses_cheap_and_precise_blame(self):
        self.write("code.py", "value = 1\n")
        self.commit(1)
        self.write("code.py", "value = 3\n")
        self.commit(3)
        expected = blame_rows(self.root, "code.py", "-C")[0][0]
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness([("code.py", 1, [1], self.timestamp(2))])
            self.assertEqual(history.stale_region_time(
                "code.py", 1, [1], since=self.timestamp(2)), expected)
        blame = [call.args[0] for call in commands.call_args_list if "blame" in call.args[0]]
        self.assertEqual(len(blame), 2, blame)
        self.assertEqual(sum("-C" in args[args.index("blame") + 1:] for args in blame), 1)

    def test_preload_keeps_unstaged_staged_and_untracked_paths(self):
        for path in ("unstaged.py", "staged.py"):
            self.write(path, "value = 1\n")
        self.commit(1)
        for path in ("unstaged.py", "staged.py", "untracked.py"):
            self.write(path, "value = 2\n")
        self.assertEqual(support.git(self.root, "add", "staged.py")[0], 0)
        paths = ["unstaged.py", "staged.py", "untracked.py"]
        before = {path: WholeFileBlame(self.root).region_time(path, 1, [1]) for path in paths}
        instant = self.timestamp(4) + 0.5
        with patch("lipi.checker.history.time.time", return_value=instant):
            history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness([(path, 1, [1], self.timestamp(2)) for path in paths])
            actual = {path: history.stale_region_time(path, 1, [1], since=self.timestamp(2))
                      for path in paths}
        for path in paths:
            with self.subTest(path=path):
                if before[path] is None:
                    self.assertIsNone(actual[path])
                else:
                    self.assertEqual(actual[path], instant)
                self.assertTrue(any("blame" in call.args[0] and call.args[0][-1] == path
                                    for call in commands.call_args_list))

    def test_preload_preserves_unusual_filenames_and_symlinks(self):
        paths = ["space name.py", "tab\tname.py", "line\nname.py", "\nleading.py", "юникод.py"]
        for path in paths:
            self.write(path, "value = 1\n")
        (self.root / "alias.py").symlink_to(paths[0])
        self.commit(1)
        for path in paths:
            self.write(path, "value = 3\n")
        self.commit(3)
        paths.append("alias.py")
        history = GitBlame(self.root)
        history.preload_staleness([(path, 1, [1], self.timestamp(2)) for path in paths])
        for path in paths:
            with self.subTest(path=path):
                expected = WholeFileBlame(self.root).stale_region_time(
                    path, 1, [1], since=self.timestamp(2))
                self.assertEqual(history.stale_region_time(
                    path, 1, [1], since=self.timestamp(2)), expected)

    def test_preload_uses_paths_relative_to_a_nested_repository_root(self):
        self.write("nested/code.py", "value = 1\n")
        self.commit(1)
        self.write("nested/code.py", "value = 3\n")
        self.commit(3)
        nested = self.root / "nested"
        expected = blame_rows(nested, "code.py", "-C")[0][0]
        history = GitBlame(nested)
        history.preload_staleness([("code.py", 1, [1], self.timestamp(2))])
        self.assertEqual(history.stale_region_time(
            "code.py", 1, [1], since=self.timestamp(2)), expected)

    def test_index_flags_cannot_hide_uncommitted_changes_from_preload(self):
        paths = {"assumed.py": "--assume-unchanged", "skipped.py": "--skip-worktree"}
        for path in paths:
            self.write(path, "value = 1\n")
        self.commit(1)
        for path, flag in paths.items():
            self.assertEqual(support.git(self.root, "update-index", flag, path)[0], 0)
            self.write(path, "value = 2\n")
        # These flags hide working tree edits from status, but not from blame.
        code, status = support.git(self.root, "status", "--porcelain=v1", "-z")
        self.assertEqual((code, status), (0, ""))
        instant = self.timestamp(4) + 0.5
        with patch("lipi.checker.history.time.time", return_value=instant):
            history = GitBlame(self.root)
        history.preload_staleness([(path, 1, [1], self.timestamp(2)) for path in paths])
        for path in paths:
            with self.subTest(path=path):
                actual = history.stale_region_time(path, 1, [1], since=self.timestamp(2))
                self.assertEqual(actual, instant)

    def test_preload_inventory_errors_fall_back_without_hiding_changes(self):
        self.write("code.py", "value = 1\n")
        self.commit(1)
        self.write("code.py", "value = 3\n")
        self.commit(3)
        expected = blame_rows(self.root, "code.py", "-C")[0][0]
        real_run = subprocess.run
        for failed_command in ("log", "status"):
            with self.subTest(command=failed_command):
                history = GitBlame(self.root)
                rejected = []

                def fail_inventory(args, **kwargs):
                    if ((failed_command == "log" and "log" in args)
                            or (failed_command == "status" and "status" in args)):
                        rejected.append(args)
                        raise subprocess.CalledProcessError(1, args)
                    return real_run(args, **kwargs)

                with patch("lipi.checker.history.subprocess.run", side_effect=fail_inventory):
                    history.preload_staleness([("code.py", 1, [1], self.timestamp(2))])
                    self.assertEqual(history.stale_region_time(
                        "code.py", 1, [1], since=self.timestamp(2)), expected)
                self.assertTrue(rejected)

    def test_suspect_regions_share_one_precise_copy_search(self):
        self.move_chunk()
        history = GitBlame(self.root)
        starts = [2, 7]
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness([
                ("target.py", start, starts, self.timestamp(2)) for start in starts])
            for start in starts:
                self.assertIsNone(history.stale_region_time(
                    "target.py", start, starts, since=self.timestamp(2), code=False))
        expensive = [call.args[0] for call in commands.call_args_list
                     if "blame" in call.args[0] and call.args[0][-1] == "target.py"
                     and "-C" in call.args[0][call.args[0].index("blame") + 1:]]
        self.assertEqual(len(expensive), 1, expensive)

    def test_limited_preload_keeps_request_order_and_unknown_regions_explicit(self):
        from lipi.checker.history import BlameIncompleteError

        paths = ("z.py", "a.py", "b.py")
        for path in paths:
            self.write(path, "changed = 1\nunchanged = 1\n")
        self.commit(1)
        for path in paths:
            self.write(path, "changed = 3\nunchanged = 1\n")
        self.commit(3)
        history = GitBlame(self.root)
        requests = [(path, start, [1, 2], self.timestamp(2)) for path in paths for start in (1, 2)]
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness(requests, max_precise_files=2)
            for path in paths:
                self.assertEqual(history.region_checked(path, 1, [1, 2], since=self.timestamp(2)), path != "b.py")
                self.assertTrue(history.region_checked(path, 2, [1, 2], since=self.timestamp(2)))
            self.assertIsNone(history.stale_region_time("b.py", 2, [1, 2], since=self.timestamp(2)))
            self.assertFalse(history.region_checked("b.py", 2, [1, 2], since=self.timestamp(1) - 1))
            before = len(commands.call_args_list)
            with self.assertRaises(BlameIncompleteError):
                history.stale_region_time("b.py", 1, [1, 2], since=self.timestamp(2))
            with self.assertRaises(BlameIncompleteError):
                history.stale_region_time("b.py", 2, [1, 2], since=self.timestamp(1) - 1)
            self.assertEqual(len(commands.call_args_list), before)
        precise = [call.args[0][-1] for call in commands.call_args_list
                   if "blame" in call.args[0] and "-C" in call.args[0][call.args[0].index("blame") + 1:]]
        self.assertEqual(set(precise), {"z.py", "a.py"})
        self.assertEqual(len(precise), 2)
        # Explicit full-history access remains available; only bounded stale queries stop.
        self.assertEqual(history.lines("b.py"), blame_rows(self.root, "b.py", "-C"))
        self.assertTrue(history.region_checked("b.py", 1, [1, 2], since=self.timestamp(2)))
        self.assertEqual(history.stale_region_time("b.py", 1, [1, 2], since=self.timestamp(2)), self.timestamp(3))

    def test_empty_cheap_file_remains_checked_without_precise_blame(self):
        self.write("empty.py", "")
        self.commit(1)
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness([("empty.py", 1, [1], self.timestamp(1) - 1)], max_precise_files=0)
            self.assertTrue(history.region_checked("empty.py", 1, [1], since=self.timestamp(1) - 1))
            before = len(commands.call_args_list)
            self.assertIsNone(history.stale_region_time("empty.py", 1, [1], since=self.timestamp(1) - 1))
            self.assertEqual(len(commands.call_args_list), before)
        precise = [call.args[0] for call in commands.call_args_list
                   if "blame" in call.args[0] and "-C" in call.args[0][call.args[0].index("blame") + 1:]]
        self.assertEqual(precise, [])

    def test_precise_priority_uses_first_file_occurrence_even_when_first_region_is_safe(self):
        for path in ("first.py", "second.py"):
            self.write(path, "unchanged = 1\nchanged = 1\n")
        self.commit(1)
        for path in ("first.py", "second.py"):
            self.write(path, "unchanged = 1\nchanged = 3\n")
        self.commit(3)
        history = GitBlame(self.root)
        history.preload_staleness([
            ("first.py", 1, [1, 2], self.timestamp(2)),
            ("second.py", 2, [1, 2], self.timestamp(2)),
            ("first.py", 2, [1, 2], self.timestamp(2)),
        ], max_precise_files=1)
        self.assertTrue(history.region_checked("first.py", 2, [1, 2], since=self.timestamp(2)))
        self.assertFalse(history.region_checked("second.py", 2, [1, 2], since=self.timestamp(2)))
        self.assertEqual(set(history.cache), {"first.py"})

    def test_cheap_limit_keeps_coarse_proofs_for_each_document_date_beyond_the_limit(self):
        from lipi.checker.history import BlameIncompleteError

        changed = ["changed_%02d.py" % n for n in range(70)]
        for path in changed + ["old.py", "documented.py", "mixed.py"]:
            self.write(path, "first_value = 1\nsecond_value = 1\n")
        self.commit(1)
        for path in ("documented.py", "mixed.py"):
            self.write(path, "first_value = 2\nsecond_value = 2\n")
        self.commit(2)
        for path in changed:
            self.write(path, "first_value = 3\nsecond_value = 1\n")
        self.commit(3)
        requests = [(path, start, [1, 2], self.timestamp(2)) for path in changed for start in (1, 2)]
        requests += [("old.py", 1, [1], self.timestamp(1)),
                     ("documented.py", 1, [1], self.timestamp(4)),
                     ("mixed.py", 1, [1, 2], self.timestamp(1)),
                     ("mixed.py", 2, [1, 2], self.timestamp(4))]
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness(requests, max_cheap_files=64, max_precise_files=16)
            for n, path in enumerate(changed):
                self.assertEqual(history.region_checked(path, 1, [1, 2], since=self.timestamp(2)), n < 16)
                self.assertEqual(history.region_checked(path, 2, [1, 2], since=self.timestamp(2)), n < 64)
            for path, start, starts, since in requests[-4:]:
                self.assertEqual(history.region_checked(path, start, starts, since=since),
                                 path != "mixed.py" or start == 2)
            before = len(commands.call_args_list)
            with self.assertRaises(BlameIncompleteError):
                history.stale_region_time(changed[64], 1, [1, 2], since=self.timestamp(2))
            self.assertIsNone(history.stale_region_time("mixed.py", 2, [1, 2], since=self.timestamp(4)))
            self.assertEqual(len(commands.call_args_list), before)
        cheap, precise = [], []
        for call in commands.call_args_list:
            args = call.args[0]
            if "blame" in args:
                (precise if "-C" in args[args.index("blame") + 1:] else cheap).append(args[-1])
        self.assertEqual(set(cheap), set(changed[:64]))
        self.assertEqual(len(cheap), 64)
        self.assertEqual(set(precise), set(changed[:16]))
        self.assertEqual(len(precise), 16)

    def test_renamed_path_consumes_cheap_budget_before_later_suspect(self):
        from lipi.checker.history import BlameIncompleteError

        self.write("original.py", "renamed_value = 1\n")
        self.write("changed.py", "changed_value = 1\n")
        self.commit(1)
        (self.root / "original.py").rename(self.root / "renamed.py")
        self.write("changed.py", "changed_value = 3\n")
        self.commit(3)
        history = GitBlame(self.root)
        with patch("lipi.checker.history.subprocess.run", wraps=subprocess.run) as commands:
            history.preload_staleness([
                ("renamed.py", 1, [1], self.timestamp(2)),
                ("changed.py", 1, [1], self.timestamp(2)),
            ], max_cheap_files=1, max_precise_files=1)
            self.assertTrue(history.region_checked("renamed.py", 1, [1], since=self.timestamp(2)))
            self.assertFalse(history.region_checked("changed.py", 1, [1], since=self.timestamp(2)))
            before = len(commands.call_args_list)
            with self.assertRaises(BlameIncompleteError):
                history.stale_region_time("changed.py", 1, [1], since=self.timestamp(2))
            self.assertEqual(len(commands.call_args_list), before)
        blame = [call.args[0] for call in commands.call_args_list if "blame" in call.args[0]]
        self.assertEqual([args[-1] for args in blame], ["renamed.py"])
        self.assertNotIn("-C", blame[0][blame[0].index("blame") + 1:])

    def test_coarse_history_includes_root_commit_and_numeric_filename(self):
        self.write("12345", "created_value = 3\n")
        self.commit(3)
        history = GitBlame(self.root)
        history.preload_staleness([
            ("12345", 1, [1], self.timestamp(2)),
            ("12345", 1, [1], self.timestamp(4)),
        ], max_cheap_files=0, max_precise_files=0)
        self.assertFalse(history.region_checked("12345", 1, [1], since=self.timestamp(2)))
        self.assertTrue(history.region_checked("12345", 1, [1], since=self.timestamp(4)))
        self.assertEqual(history.cheap_cache, {})
        self.assertEqual(history.cache, {})


if __name__ == "__main__":
    unittest.main()
