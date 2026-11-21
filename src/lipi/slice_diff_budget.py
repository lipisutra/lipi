"""Keep changed contract lines within the slice excerpt budget."""

from collections import deque
from difflib import SequenceMatcher
from itertools import chain, islice, zip_longest


SIDES = ("before", "after")


def _line_count(text):
    # Excerpts are LF-joined snapshot rows, so a trailing LF keeps a blank row.
    return text.count("\n") + 1 if text else 0


def section_line_count(sections):
    return sum(_line_count(section[side]) for section in sections for side in SIDES)


def _change_spans(before, after):
    # Match the shared edges explicitly so repeated text at the end remains
    # context even when SequenceMatcher ignores popular lines in long slices.
    shared = min(len(before), len(after))
    start = suffix = 0
    while start < shared and before[start] == after[start]:
        start += 1
    while suffix < shared - start and before[-suffix - 1] == after[-suffix - 1]:
        suffix += 1
    matcher = SequenceMatcher(None, before[start:len(before) - suffix],
                              after[start:len(after) - suffix])
    left, right = [], []
    for kind, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if kind != "equal":
            left.append(range(start + old_start, start + old_end))
            right.append(range(start + new_start, start + new_end))
    return left, right


def _preferred_rows(rows, spans):
    context = range(len(rows))
    if spans:
        # Nearby context helps on the unchanged side of an insertion or deletion.
        before = range(spans[0].start - 1, -1, -1)
        gaps = (range(left.stop, right.start) for left, right in zip(spans, spans[1:]))
        after = chain(chain.from_iterable(gaps), range(spans[-1].stop, len(rows)))
        context = (number for neighbors in zip_longest(before, after)
                   for number in neighbors if number is not None)

    # A single displayed blank row would look the same as a fully hidden side.
    blank = []
    for changed, numbers in ((True, chain.from_iterable(spans)), (False, context)):
        for number in numbers:
            candidate = (number, rows[number], changed)
            if rows[number].strip():
                yield candidate
            else:
                blank.append(candidate)
    yield from blank


def _section_rows(section):
    rows = [section[side].split("\n") if section[side] else [] for side in SIDES]
    spans = _change_spans(*rows) if all(rows) else ((), ())
    candidates = (_preferred_rows(side_rows, changes) for side_rows, changes in zip(rows, spans))
    for pair in zip_longest(*candidates):
        visible = [(side, row) for side, row in zip(SIDES, pair) if row is not None]
        # For a single remaining line, prefer the changed side of an insertion or deletion.
        yield sorted(visible, key=lambda item: not item[1][2])


def _rounds(sections):
    pending = deque((index, _section_rows(section)) for index, section in enumerate(sections))
    while pending:
        index, rows = pending.popleft()
        pair = next(rows, None)
        if pair is not None:
            for side, (number, text, _) in pair:
                yield index, side, (number, text)
            pending.append((index, rows))


# @trace docs/ru/slice-output.md#budget
def trim_sections(diff, limit):
    """Set selected lines and omission counts on a diff known to be over budget."""
    sections = diff["sections"]
    selected = {}
    for index, side, row in islice(_rounds(sections), limit):
        selected.setdefault(index, {}).setdefault(side, []).append(row)

    displayed = []
    for index, section in enumerate(sections):
        if index not in selected:
            continue
        section = dict(section)
        omitted = {}
        for side in SIDES:
            rows = selected[index].get(side, ())
            original = section[side]
            omitted[side] = _line_count(original) - len(rows)
            if omitted[side]:
                section[side] = "\n".join(line for _, line in sorted(rows))
        if any(omitted.values()):
            section["omitted"] = omitted
        displayed.append(section)

    diff["sections"] = displayed
    if len(displayed) < len(sections):
        diff["sections_omitted"] = len(sections) - len(displayed)
