"""Match changed Markdown lines to explicit anchor regions on both Git sides."""

from pathlib import Path
from urllib.parse import unquote

from .checker.model import Page, anchor_region, is_within


def local_section_address(pr, token):
    """Return the lexical path and anchor of a local section marker."""
    page, separator, anchor = token.partition('#')
    if not separator or not page or not anchor or '::' in token:
        return None
    path = Path(unquote(page))
    if path.is_absolute():
        return None
    path = pr.lexical_path(path)
    if is_within(path, pr.root):
        return pr.rel(path), unquote(anchor)
    return None


def _regions(path, rows):
    if path is None or not rows:
        return {}
    # Page splits on LF. Keep a final blank physical row if the snapshot has one.
    page = Page(path, '\n'.join(rows) + '\n')
    duplicates = {anchor for _, anchor in page.dup}
    return {anchor: anchor_region(page, line)
            for line, anchor in page.anchor_order if anchor and anchor not in duplicates}


def _touched(regions, changes):
    if not regions:
        return set(), [int(bool(change)) for change in changes]
    changed = {line for change in changes for line in change}
    touched, covered = set(), set()
    for anchor, region in regions.items():
        if not changed.isdisjoint(region):
            touched.add(anchor)
            covered.update(region)
    outside = [sum(line not in covered and (line == change.start or line - 1 in covered)
                   for line in change) for change in changes]
    return touched, outside


def _excerpts(path, rows, regions, touched):
    return {path.as_posix() + '#' + anchor: [rows[line - 1] for line in regions[anchor]]
            for anchor in touched & regions.keys()}


# @trace docs/ru/slice-diff.md#selection
def section_changes(old_path, before, new_path, after, hunks):
    """Return excerpts, the unanchored count, and valid anchors on both Git sides."""
    old_path = Path(old_path) if old_path is not None else None
    new_path = Path(new_path) if new_path is not None else None
    old_regions, new_regions = _regions(old_path, before), _regions(new_path, after)
    old_changes = [range(old, old + (removed if old_path is not None else 0))
                   for old, removed, _, _ in hunks]
    new_changes = [range(new, new + (added if new_path is not None else 0))
                   for _, _, new, added in hunks]
    old_touched, old_outside = _touched(old_regions, old_changes)
    new_touched, new_outside = _touched(new_regions, new_changes)
    # Within one Git record, the same anchor on the other side also belongs
    # to the change. A file rename still gives the two excerpts distinct addresses.
    touched = old_touched | new_touched
    old_excerpts = _excerpts(old_path, before, old_regions, touched)
    new_excerpts = _excerpts(new_path, after, new_regions, touched)
    sections = {address: {'before': old_excerpts.get(address), 'after': new_excerpts.get(address)}
                for address in sorted(old_excerpts.keys() | new_excerpts.keys())}
    outside = sum(max(left, right) for left, right in zip(old_outside, new_outside))
    return sections, outside, set(old_regions), set(new_regions)
