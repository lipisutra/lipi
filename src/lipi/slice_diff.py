"""Read-only Git changes and their explicit links in the current slice index."""

import os
import re
import subprocess
from pathlib import Path

from .i18n import tr
from .checker.conventions import MAX_CODE_FILE
from .checker.marks import physical_lines, trace_matches
from .slice_index import SliceIndex

HUNK = re.compile(rb'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', re.M)


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


def _records(data):
    """NUL-delimited raw names avoid Git's quoting and unusual-path ambiguity."""
    if not data:
        return []
    raw, separator, patch = data.partition(b'\0\0')
    if not separator:
        raise ValueError(tr('slice.git.incomplete_diff'))
    fields, records, pos = raw.split(b'\0'), [], 0
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
        records.append((old_path, new_path, old_mode[1:], new_mode, old_oid, new_oid))
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


def _text(data):
    if len(data) > MAX_CODE_FILE or b'\0' in data:
        return None
    try:
        return physical_lines(data.decode('utf-8'))
    except UnicodeDecodeError:
        return None


def _snapshot(pr, path, oid, mode, working=False):
    if mode == b'000000':
        return []
    if mode not in (b'100644', b'100755'):
        return None
    if working:
        source = pr.file_path(path)
        if source != pr.root / path:
            return None
        try:
            if source.is_symlink() or source.stat().st_size > MAX_CODE_FILE:
                return None
            return _text(source.read_bytes())
        except OSError as error:
            raise ValueError(tr('slice.git.read') % (path, error)) from error
    if int(_git(pr.root, 'cat-file', '-s', oid.decode('ascii'))) > MAX_CODE_FILE:
        return None
    return _text(_git(pr.root, 'cat-file', 'blob', oid.decode('ascii')))


def _groups(index, rows):
    groups = []
    for line, row in enumerate(rows, 1):
        matches = list(trace_matches(row))
        if not matches:
            continue
        targets = {target for match in matches for token in match[1].split(',')
                   for target in [index.mark(token.strip())] if target}
        standalone = SliceIndex._standalone(row)
        if groups and standalone and groups[-1]['standalone'] and groups[-1]['end'] + 1 == line:
            groups[-1]['end'] = line
            groups[-1]['targets'].update(targets)
        else:
            groups.append({'start': line, 'end': line, 'standalone': standalone,
                           'targets': targets})
    for pos, group in enumerate(groups):
        group['stop'] = groups[pos + 1]['start'] - 1 if pos + 1 < len(groups) else len(rows)
    return groups


def _touched(groups, start, count):
    if not count:
        return [], 0
    end = start + count - 1
    touched = [group for group in groups if group['start'] <= end and group['stop'] >= start]
    # Unresolved markers break ownership just like resolved marker boundaries.
    # Consecutive unresolved regions are one continuous unmarked interval.
    marked = [(max(start, group['start']), min(end, group['stop']))
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
            last = min(old + length, group['stop'])
            if first >= last:
                continue
            first_line, last_line = new + first - old + 1, new + last - old
            for owner in destination:
                if owner['start'] <= last_line and owner['stop'] >= first_line:
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
    mapped = _mapped_groups(groups, _unchanged(rows, _hunks(patch)), _groups(index, current))
    return {(path, group['start']) for group in mapped.values() if group['targets']}


# @trace docs/ru/slice-diff.md#selection
def collect_diff(index, base=None, staged=False):
    """Collect seeds and changed declarations without checks or Git writes.

    Each zero-context hunk contributes max(old_unmarked, new_unmarked), where
    each side counts continuous changed intervals without a resolvable marker.
    A replacement therefore does not count the same unmarked place twice.
    Historical and staged markers always resolve against the current index.
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
    result = {'seeds': set(), 'changed': set(), 'unmarked': 0, 'files': 0}
    for record, patch in _records(_git(root, *arguments, '--')):
        old_path, path, old_mode, new_mode, old_oid, new_oid = record
        old_code, new_code = _code_path(index.pr, old_path), _code_path(index.pr, path)
        if not old_code and not new_code:
            continue
        before = _snapshot(index.pr, old_path, old_oid, old_mode) if old_code else []
        after = _snapshot(index.pr, path, new_oid, new_mode, working=not staged) if new_code else []
        # Binary/oversize transitions are not code changes, on either edge.
        if before is None or after is None or b'Binary files ' in patch:
            continue
        result['files'] += 1
        old_groups, new_groups = _groups(index, before), _groups(index, after)
        old_touched, new_touched = {}, {}
        hunks = _hunks(patch)
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
