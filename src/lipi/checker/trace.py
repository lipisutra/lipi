"""Метки кода и расхождение с описанием."""

import re
import subprocess

from lipi.i18n import quoted, tr
from .config import code_layer, is_configured_test_file
from .conventions import MAX_CODE_FILE
from .marks import ignores_trace, physical_lines, trace_groups, trace_matches, trace_roles
from .model import Page, anchor_region, read_text
from .targets import check_target_status, normalize_work_id, resolve_mark, target_error_code


# --- Код ---------------------------------------------------------------------

# @trace docs/ru/codes.md#t5
def _trace_role_errors(match, targets, is_test):
    roles, invalid_roles = trace_roles(match)
    errors = dict.fromkeys(invalid_roles, "checker.trace.invalid_role")
    if roles:
        if is_test:
            errors.update(dict.fromkeys(roles, "checker.trace.role_on_test"))
        elif any(normalize_work_id(target.split("::", 1)[-1]) for target in targets):
            errors.update(dict.fromkeys(roles, "checker.trace.role_on_work_id"))
    return errors


# @trace docs/ru/codes.md#t1
def scan_code(pr, rep, *, tag_groups=None):
    """Построчные связи для графа и по запросу группы для проверки T2."""
    tags, tag_lines = {}, {}
    pr.ignored_trace_lines = 0
    skip = set(x for x in (pr.docs, pr.wf, pr.decisions) if x is not None)
    for p in pr.walk_files(skip=skip, resolved=True):
        if p.name.lower().endswith(".md"):
            continue
        try:
            if p.stat().st_size > MAX_CODE_FILE:
                continue
        except OSError:
            continue
        text = read_text(p)
        if text is None or ("@trace" not in text and not ignores_trace(text)):
            continue
        r, rows = pr.rel(p), physical_lines(text)
        is_test = is_configured_test_file(r, code_layer(r, pr.cfg), pr.cfg)
        resolved_targets = {}
        for n, s in enumerate(rows, 1):
            pr.ignored_trace_lines += int(ignores_trace(s))
            role_errors = {}
            for m in trace_matches(s):
                ids = []
                targets = [token.strip() for token in m.group(1).split(",")]
                role_errors.update(_trace_role_errors(m, targets, is_test))
                for target in targets:
                    i, err = resolve_mark(pr, target)
                    if i is None:
                        # @trace docs/ru/codes.md#t1,docs/ru/codes.md#t4
                        rep.finding(target_error_code(err, "T1"), r, n,
                                    "@trace: %s" % err, subject=target)
                    else:
                        # @trace docs/ru/codes.md#t3
                        check_target_status(pr, rep, i, r, n)
                        # @trace docs/ru/codes.md#t1
                        ids.append(i)
                        if tag_groups is not None:
                            resolved_targets[target] = i
                        tags.setdefault(i, []).append((r, n))
                tag_lines.setdefault(r, []).append((n, ids))
            for value, message in role_errors.items():
                rep.finding("T5", r, n, tr(message) % quoted(value), subject=value)
        if tag_groups is not None and r in tag_lines:
            tag_groups[r] = trace_groups(rows, resolved_targets.get)
    return tags, tag_lines


def touched_places(ranges, groups):
    """Цели затронутых групп с фактическими строками меток."""
    for group in groups:
        if any(a <= group['region_end'] and b >= group['start'] for a, b in ranges):
            yield from group['targets'].items()


# @trace docs/ru/codes.md#t2
class ChangedRanges(list):
    """Диапазоны кода плюс точные стороны diff для областей Markdown."""

    def __init__(self, previous_oid):
        super().__init__()
        self.previous_oid = previous_oid
        self.current = []
        self.previous = []
        self.previous_page = None


def touched_anchors(ranges, page):
    """Якоря, в точные области которых попали изменённые строки."""
    snapshots = [(page, ranges)]
    if isinstance(ranges, ChangedRanges):
        snapshots = [(page, ranges.current)]
        if ranges.previous_page is not None:
            snapshots.append((ranges.previous_page, ranges.previous))
    return sorted({aid for snapshot, changes in snapshots
                   for line, aid in snapshot.anchor_order
                   if any(a <= selected <= b for selected in anchor_region(snapshot, line)
                          for a, b in changes)})


def git_changed(pr, args):
    """Изменённые файлы: {путь: [(начало, конец), ...]} для областей кода.

    ChangedRanges также сохраняет обе стороны hunks: удалённые строки
    Markdown проверяются по исходному документу, добавленные — по текущему.
    """
    cmd = ["git", "-C", str(pr.root), "diff", "-U0", "--no-color", "--relative",
           "--full-index"]
    cmd += ["--cached"] if args.staged else [args.diff]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
                         ).stdout.decode("utf-8", "replace")
    changed, cur, previous_oid = {}, None, None
    for s in out.split("\n"):
        if s.startswith("diff --git "):
            cur, previous_oid = None, None
        elif s.startswith("index "):
            previous_oid = s.split()[1].partition("..")[0]
        elif s.startswith("+++ "):
            cur = s[6:] if s.startswith("+++ b/") else None
            if cur:
                changed.setdefault(cur, ChangedRanges(previous_oid))
        elif s.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", s)
            if m:
                old, removed = int(m[1]), int(m[2] or 1)
                a, n = int(m[3]), int(m[4] or 1)
                ranges = changed[cur]
                ranges.append((a, a + max(n, 1) - 1))
                if n:
                    ranges.current.append((a, a + n - 1))
                if removed:
                    ranges.previous.append((old, old + removed - 1))
    for path, ranges in changed.items():
        if not path.lower().endswith('.md') or not ranges.previous or not ranges.previous_oid:
            continue
        # Blob из самого diff верен для --cached и любых диапазонов ревизий,
        # включая merge-base у A...B. Удаление относится к его старым строкам,
        # а не к соседней строке, которую Git указывает в пустой стороне +N,0.
        before = subprocess.run(
            ["git", "-C", str(pr.root), "cat-file", "blob", ranges.previous_oid],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        ).stdout.decode("utf-8", "replace")
        ranges.previous_page = Page(pr.root / path, before)
    return changed


# @trace docs/ru/codes.md#t2
def check_drift(pr, rep, pages, anchor_ids, covers, tag_groups, changed):
    code_touched = {}
    for f, ranges in changed.items():
        for i, _ in touched_places(ranges, tag_groups.get(f, [])):
            if i not in pr.mark_external:
                code_touched.setdefault(i, f)
    docs_touched = set()
    for page in {page for aid, (page, _) in anchor_ids.items() if aid not in pr.mark_external}:
        ranges = changed.get(pr.rel(page.path))
        if ranges:
            rel = pr.rel(page.path)
            docs_touched.update("%s#%s" % (rel, aid)
                                for aid in touched_anchors(ranges, page))
    for i, f in sorted(code_touched.items()):
        if i in anchor_ids and i not in docs_touched:
            page, line = anchor_ids[i]
            rep.finding("T2", f, 0, tr("checker.trace.stale_anchor_region") % (i, pr.rel(page.path), line), subject=i)
    for i in sorted(docs_touched):
        for page in covers.get(i, []):
            if pr.rel(page.path) not in changed:
                rep.finding("T2", pr.rel(page.path), 0, tr("checker.trace.stale_reference_page") % i, subject=i)
