"""Read-only Git changes and their explicit links in the current slice index."""

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from .i18n import tr
from .checker.conventions import MAX_CODE_FILE
from .checker.marks import physical_lines, trace_groups
from .checker.model import is_within
from .checker.targets import decision_path_id, target_excluded
from .slice_diff_sections import local_section_address, section_changes

HUNK = re.compile(rb'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', re.M)
REGULAR_MODES = (b'100644', b'100755')


def _git(root, *args):
    try:
        result = subprocess.run(['git', '-C', str(root), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    except OSError as error:
        raise ValueError(tr('slice.git.unavailable') % error) from error
    if result.returncode:
        raise ValueError('Git: %s' % result.stderr.decode('utf-8', 'replace').strip())
    return result.stdout


def _raw_records(raw):
    """NUL-delimited raw names avoid Git's quoting and unusual-path ambiguity."""
    if not raw:
        return
    fields, pos = raw.removesuffix(b'\0').split(b'\0'), 0
    while pos < len(fields):
        header = fields[pos].split()
        if len(header) != 5 or not header[0].startswith(b':'):
            raise ValueError(tr('slice.git.invalid_header'))
        old_mode, new_mode, old_oid, new_oid, status = header
        if status.startswith(b'U'):
            raise ValueError(tr('slice.git.conflict'))
        pos += 1
        old_path = new_path = os.fsdecode(fields[pos])
        pos += 1
        if status[:1] in (b'R', b'C'):
            new_path = os.fsdecode(fields[pos])
            pos += 1
        yield old_path, new_path, old_mode[1:], new_mode, old_oid, new_oid, status


def _records(data):
    if not data:
        return []
    raw, separator, patch = data.partition(b'\0\0')
    if not separator:
        raise ValueError(tr('slice.git.incomplete_diff'))
    records = []
    for old_path, new_path, old_mode, new_mode, old_oid, new_oid, status in _raw_records(raw):
        if status == b'T':
            # Git emits separate patches for the old and new entry.
            records.append((old_path, old_path, old_mode, b'000000', old_oid, b'0'))
            records.append((new_path, new_path, b'000000', new_mode, b'0', new_oid))
        else:
            records.append((old_path, new_path, old_mode, new_mode, old_oid, new_oid))
    patches = re.split(rb'^diff --git ', patch, flags=re.M)[1:]
    if len(records) != len(patches):
        raise ValueError(tr('slice.git.inconsistent_diff'))
    return list(zip(records, patches))


def _code_path(pr, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or path.suffix.lower() == '.md':
        return False
    absolute = pr.root / path
    if (pr.skip_dirs.excludes(absolute) or pr.sources.local.is_archived(absolute)
            or pr.in_connected_repo(absolute)):
        return False
    # Use configured paths even if the last file in a directory was deleted.
    directories = [pr.docs, pr.wf, pr.decisions]
    directories += [pr.lexical_path(pr.cfg[key]) for key in ('docs', 'workflow', 'decisions')
                    if pr.cfg.get(key)]
    return not any(directory and directory != pr.root and
                   (absolute == directory or directory in absolute.parents)
                   for directory in directories)


def _text(data, *, markdown=False):
    if (not markdown and len(data) > MAX_CODE_FILE) or b'\0' in data:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    if markdown:
        text = text.replace('\r\n', '\n')
    return physical_lines(text)


def _snapshot(pr, path, oid, mode, working=False, *, markdown=False):
    if mode == b'000000':
        return []
    if mode not in REGULAR_MODES:
        return None
    if working:
        source = pr.file_path(path)
        if source != pr.root / path:
            return None
        try:
            if source.is_symlink() or (not markdown and source.stat().st_size > MAX_CODE_FILE):
                return None
            data = source.read_bytes()
        except OSError as error:
            raise ValueError(tr('slice.git.read') % (path, error)) from error
    else:
        blob = oid.decode('ascii')
        if not markdown and int(_git(pr.root, 'cat-file', '-s', blob)) > MAX_CODE_FILE:
            return None
        data = _git(pr.root, 'cat-file', 'blob', blob)
    return _text(data, markdown=markdown)


def _document_allowed(pr, path):
    return not target_excluded(pr, path) and not pr.sources.local.is_archived(path)


def _document_snapshot(pr, relative, oid, mode, working=False):
    if mode not in REGULAR_MODES or Path(relative).suffix.lower() != '.md':
        return None, []
    if not _document_allowed(pr, pr.lexical_path(relative)):
        return None, []
    rows = _snapshot(pr, relative, oid, mode, working=working, markdown=True)
    return (relative, rows) if rows is not None else (None, [])


def _collect_documents(pr, result, record, hunks, staged):
    old_path, new_path, old_mode, new_mode, old_oid, new_oid = record
    old, before = _document_snapshot(pr, old_path, old_oid, old_mode)
    new, after = _document_snapshot(pr, new_path, new_oid, new_mode, working=not staged)
    if old is None and new is None:
        return {}, {}
    sections, outside, old_anchors, new_anchors = section_changes(old, before, new, after, hunks)
    result.setdefault('sections', {}).update(sections)
    result['unanchored'] = result.get('unanchored', 0) + outside
    paths = result.setdefault('document_paths', set())
    paths.update(path for path in (old, new) if path is not None)
    return (
        {old: old_anchors} if old is not None else {},
        {new: new_anchors} if new is not None else {},
    )


def _snapshot_mark(index, document_paths, snapshot):
    @lru_cache(maxsize=None)
    def resolve(token):
        parts = local_section_address(index.pr, token)
        if parts is not None and parts[0] in document_paths:
            path, anchor = parts
            return '#'.join(parts) if anchor in snapshot.get(path, ()) else None
        return index.mark(token)

    return resolve


def _decision_files(pr, directory, *, revision, staged):
    if not staged and revision is None:
        yield from (path for path in pr.walk_md(directory, exclusions=pr.target_skip_dirs)
                    if pr.file_path(path) == path)
        return
    pathspec = ':(literal)' + pr.rel(directory)
    args = ['ls-files', '--stage', '-z'] if staged else ['ls-tree', '-r', '-z', revision]
    for row in _git(pr.root, *args, '--', pathspec).split(b'\0'):
        fields, _, name = row.partition(b'\t')
        if fields.partition(b' ')[0] in REGULAR_MODES and (not staged or fields.endswith(b' 0')):
            yield pr.root / os.fsdecode(name)


def _changed_decisions(pr, changed_paths, *, revision=None, staged=False):
    workflow = pr.cfg.get('workflow')
    configured = pr.cfg.get('decisions', Path(workflow) / 'adr' if workflow else None)
    if not changed_paths or configured is None:
        return set()
    directory = pr.lexical_path(configured)
    if not is_within(directory, pr.root):
        return set()
    changed = {identifier: pr.root / relative for relative in changed_paths
               if (identifier := decision_path_id(directory, pr.root / relative)) is not None}
    if not changed:
        return set()
    candidates = {}
    for path in _decision_files(pr, directory, revision=revision, staged=staged):
        identifier = decision_path_id(directory, path)
        if identifier in changed and _document_allowed(pr, path):
            candidates.setdefault(identifier, set()).add(path)
    return {identifier for identifier, path in changed.items()
            if candidates.get(identifier) == {path}}


def _code_snapshot(old_path, new_path, before, after, hunks):
    return {'old_path': old_path, 'new_path': new_path,
            'before': before, 'after': after, 'hunks': hunks}


def _staged_worktree(pr, staged_paths, snapshots):
    """Keep the unchanged index version of a file with worktree-only edits."""
    untracked = _git(pr.root, 'ls-files', '--others', '--exclude-standard', '-z', '--', '.')
    dirty_paths = {os.fsdecode(path) for path in untracked.split(b'\0') if path}
    raw = _git(pr.root, 'diff', '--raw', '-z', '--no-abbrev', '--no-renames', '--relative', '--')
    for path, _, mode, _, oid, _, _ in _raw_records(raw):
        dirty_paths.add(path)
        if path in staged_paths or mode not in REGULAR_MODES or not _code_path(pr, path):
            continue
        rows = _snapshot(pr, path, oid, mode)
        if rows is not None:
            snapshots.append(_code_snapshot(path, path, rows, rows, []))
    return dirty_paths


def _touched(groups, start, count):
    if not count:
        return [], 0
    end = start + count - 1
    touched = [group for group in groups if group['start'] <= end and group['region_end'] >= start]
    # Unresolved markers break ownership just like resolved marker boundaries.
    # Consecutive unresolved regions are one continuous unmarked interval.
    marked = [(max(start, group['start']), min(end, group['region_end']))
              for group in touched if group['targets']]
    cursor, unmarked = start, 0
    for first, last in marked:
        if first > cursor:
            unmarked += 1
        cursor = last + 1
    return touched, unmarked + int(cursor <= end)


def _hunks(patch):
    return [tuple(int(value) if value is not None else 1 for value in match.groups())
            for match in HUNK.finditer(patch)]


def _unchanged(rows, hunks):
    """Exact unchanged intervals from Git; repeated lines cannot steal ownership."""
    blocks, old_cursor, new_cursor = [], 0, 0
    for old, removed, new, added in hunks:
        old_start = old - int(removed > 0)
        new_start = new - int(added > 0)
        length = old_start - old_cursor
        if length > 0:
            blocks.append((old_cursor, new_cursor, length))
        old_cursor, new_cursor = old_start + removed, new_start + added
    if old_cursor < len(rows):
        blocks.append((old_cursor, new_cursor, len(rows) - old_cursor))
    return blocks


def _mapped_groups(groups, blocks, destination):
    found = {}
    for group in groups:
        for old, new, length in blocks:
            first = max(old, group['start'] - 1)
            last = min(old + length, group['region_end'])
            if first >= last:
                continue
            first_line, last_line = new + first - old + 1, new + last - old
            for owner in destination:
                if owner['start'] <= last_line and owner['region_end'] >= first_line:
                    found[owner['start']] = owner
    return found


def _current_places(index, path, rows, groups, staged):
    """Translate staged regions through exact index-to-working-tree hunks."""
    if not groups or not index.by_file.get(path):
        return set()
    if not staged:
        return {(path, group['start']) for group in groups if group['targets']}
    working = index.pr.file_path(path)
    if working != index.pr.root / path:
        return set()
    try:
        current = _text(working.read_bytes())
    except OSError:
        return set()
    if current is None:
        return set()
    patch = _git(index.pr.root, 'diff', '-U0', '--inter-hunk-context=0',
                 '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames',
                 '--relative', '--', ':(literal)' + path)
    mapped = _mapped_groups(groups, _unchanged(rows, _hunks(patch)), trace_groups(current, index.mark))
    return {(path, group['start']) for group in mapped.values() if group['targets']}


# @trace docs/ru/slice-diff.md#selection
def collect_diff(index, base=None, staged=False):
    """Collect seeds and changed declarations without checks or Git writes.

    Each zero-context hunk contributes max(old_unmarked, new_unmarked), where
    each side counts continuous changed intervals without a resolvable marker.
    A replacement therefore does not count the same unmarked place twice.
    Markers on changed Markdown pages resolve against the corresponding Git
    snapshot. Other targets still resolve against the current slice index.
    """
    if staged == (base is not None):
        raise ValueError(tr('slice.arguments.diff'))
    root = index.pr.root
    if _git(root, 'rev-parse', '--is-inside-work-tree').strip() != b'true':
        raise ValueError(tr('slice.git.worktree'))
    revision = []
    if not staged:
        if not isinstance(base, str) or not base or base.startswith('-') or '\0' in base:
            raise ValueError(tr('slice.git.base'))
        revision = [_git(root, 'rev-parse', '--verify', '--end-of-options',
                         base + '^{commit}').decode('ascii').strip()]
    arguments = ['diff', '--raw', '-z', '--patch', '--no-abbrev', '--full-index',
                 '-U0', '--inter-hunk-context=0', '--no-color', '--no-ext-diff',
                 '--no-textconv', '--find-renames', '--relative']
    arguments += ['--cached'] if staged else revision
    patches = _records(_git(root, *arguments, '--'))
    records = [(record, patch, _hunks(patch)) for record, patch in patches]
    result = {'seeds': set(), 'changed': set(), 'unmarked': 0, 'files': 0}
    old_documents, new_documents = {}, {}
    for record, _, hunks in records:
        if hunks and any(path.lower().endswith('.md') for path in record[:2]):
            old, new = _collect_documents(index.pr, result, record, hunks, staged)
            old_documents.update(old)
            new_documents.update(new)
    old_mark = new_mark = index.mark
    snapshots = None
    if 'document_paths' in result:
        old_mark = _snapshot_mark(index, result['document_paths'], old_documents)
        new_mark = _snapshot_mark(index, result['document_paths'], new_documents)
        result['decisions'] = _changed_decisions(
            index.pr, old_documents, revision='HEAD' if staged else revision[0])
        result['decisions'].update(_changed_decisions(index.pr, new_documents, staged=staged))
        snapshots = result['code_snapshots'] = []
        if staged:
            staged_paths = {path for record, _, _ in records for path in record[:2]}
            result['worktree_only_paths'] = _staged_worktree(index.pr, staged_paths, snapshots)
    for record, patch, hunks in records:
        old_path, path, old_mode, new_mode, old_oid, new_oid = record
        old_code, new_code = _code_path(index.pr, old_path), _code_path(index.pr, path)
        if not old_code and not new_code:
            continue
        before = _snapshot(index.pr, old_path, old_oid, old_mode) if old_code else []
        after = _snapshot(index.pr, path, new_oid, new_mode, working=not staged) if new_code else []
        binary_patch = b'Binary files ' in patch
        if snapshots is not None:
            old = old_path if old_code and old_mode in REGULAR_MODES and before is not None else None
            new = path if new_code and new_mode in REGULAR_MODES and after is not None else None
            if (old or new) and (hunks or not binary_patch or old is None or new is None):
                snapshots.append(_code_snapshot(old, new, before or [], after or [], hunks))
        # Counters keep their existing scope when either snapshot is excluded.
        if before is None or after is None or binary_patch:
            continue
        result['files'] += 1
        old_groups, new_groups = trace_groups(before, old_mark), trace_groups(after, new_mark)
        old_touched, new_touched = {}, {}
        for old, removed, new, added in hunks:
            left, left_unmarked = _touched(old_groups, old, removed) if old_code else ([], 0)
            right, right_unmarked = _touched(new_groups, new, added) if new_code else ([], 0)
            result['unmarked'] += max(left_unmarked, right_unmarked)
            old_touched.update((group['start'], group) for group in left)
            new_touched.update((group['start'], group) for group in right)
            for group in left + right:
                result['seeds'].update(group['targets'])
        new_touched.update(_mapped_groups(old_touched.values(),
                                          _unchanged(before, hunks), new_groups))
        result['changed'].update(_current_places(index, path, after, new_touched.values(), staged))
    return result
