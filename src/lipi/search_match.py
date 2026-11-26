"""Rank explicit slice search matches in one document index."""

import html
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from heapq import heappop, heappush
from math import fsum

from .checker.markdown_links import _destination
from .checker.marks import physical_lines
from .checker.model import anchor_region
from .slice_index import HEADING, clean_title, document_address

WORD = re.compile(r'[^\W_]+')
QUOTE = re.compile(r'^[ \t]*(?:>[ \t]?)+')
ITEM = re.compile(r'^([ \t]*)(?:[-+*]|\d+[.)])[ \t]+')
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)')
RULE = re.compile(r'^[ \t]*(?:(?:[-*_][ \t]*){3,}|=+[ \t]*)$')
REFERENCE = re.compile(r'^ {0,3}\[[^\]\n]+\]:[ \t]*')
LINK_END = re.compile(r"""\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))?\s*\)""")
CODE = r'(?<!`)(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)'
HIDDEN = re.compile(r'\\.|' + CODE + r'|(?P<comment><!--.*?(?:-->|$))')
INLINE = re.compile(
    r'\\.|' + CODE + r'|!?\[(?P<label>(?:\\.|[^\[\]\\]|\[[^\]]*\])*)\]'
    r'|<(?P<autolink>[\w.+-]+:[^<>\s]+|[^<>\s@]+@[^<>\s@]+)>')
EXCERPT_LENGTH = 180


def _without_comments(row, comment):
    if comment:
        _, end, row = row.partition('-->')
        if not end:
            return '', True
        comment = False
    pieces, start = [], 0
    for match in HIDDEN.finditer(row):
        if match['comment'] is not None:
            pieces.append(row[start:match.start()])
            start = match.end()
            comment = not match[0].endswith('-->')
    pieces.append(row[start:])
    return ''.join(pieces), comment


def _link_end(row, start):
    if row[start:start + 1] == '(':
        if empty := re.match(r'\s*\)', row[start + 1:]):
            return start + 1 + empty.end()
        span = _destination(row, start + 1)
        if span:
            end = span[1] + (row[span[1]:span[1] + 1] == '>')
            tail = LINK_END.match(row, end)
            if tail:
                return tail.end()
    if row[start:start + 1] == '[':
        end = row.find(']', start + 1)
        if end != -1:
            return end + 1
    return start


def _visible_inline(row):
    chunks, start = [], 0
    for match in INLINE.finditer(row):
        if match.start() < start:
            continue
        end = match.end()
        if match['label'] is not None:
            end = _link_end(row, end)
            if end == match.end():
                continue
            label = _visible_inline(match['label'])
        elif match['autolink'] is not None:
            label = match['autolink']
        else:
            continue
        chunks.extend((row[start:match.start()], label))
        start = end
    chunks.append(row[start:])
    return unicodedata.normalize('NFC', html.unescape(clean_title(''.join(chunks))))


def _paragraphs(page):
    """Yield visible paragraphs with their original physical line numbers."""
    paragraph, fence, comment = [], None, False
    list_indents, previous_blank, indented_code, previous_quote = [], True, False, False
    for line, raw in enumerate(physical_lines(page.text), 1):
        row, quoted = QUOTE.subn('', raw)
        if fence is not None:
            marker = FENCE.match(row)
            if (marker and not marker[2].strip() and marker[1][0] == fence[0]
                    and len(marker[1]) >= len(fence)):
                fence = None
            continue
        row, comment = _without_comments(row, comment)
        item = ITEM.match(row)
        indent = len(row.expandtabs(4)) - len(row.expandtabs(4).lstrip())
        if row.strip():
            while list_indents and indent < list_indents[-1]:
                list_indents.pop()
        base = list_indents[-1] if list_indents else 0
        indented_code = indent >= base + 4 and (previous_blank or indented_code)
        previous_blank = not row.strip()
        if item and not indented_code:
            list_indents.append(len(item[0].expandtabs(4)))
        marker = FENCE.match(row[item.end():] if item else row)
        if marker and not indented_code:
            fence = marker[1]
        table = row.lstrip().startswith('|')
        standalone = bool(HEADING.match(row.lstrip())) or table
        hidden = (fence is not None or indented_code or RULE.fullmatch(row)
                  or REFERENCE.match(row) or (table and RULE.fullmatch(row.replace('|', '').replace(':', ''))))
        if paragraph and (hidden or previous_blank or item or standalone or quoted != previous_quote):
            yield paragraph
            paragraph = []
        if not hidden and not previous_blank:
            visible = _visible_inline(row.lstrip())
            if table:
                visible = visible.strip('| ').replace(' | ', ' · ')
            if visible:
                if standalone:
                    yield [(line, visible)]
                else:
                    paragraph.append((line, visible))
        previous_quote = quoted
    if paragraph:
        yield paragraph


def _word_spans(text):
    end = 0
    for match in WORD.finditer(text):
        if match.start() < end:
            continue
        start, end = match.span()
        # An accent or vowel sign belongs to the surrounding word even when
        # NFC cannot represent the combination as a single character.
        if end < len(text) and unicodedata.category(text[end]).startswith('M'):
            end += 1
            while end < len(text):
                character = text[end]
                if not (character.isalnum() or unicodedata.category(character).startswith('M')):
                    break
                end += 1
        yield start, end


@dataclass(frozen=True)
class _WordMatch:
    exact: bool
    start: int
    end: int


class _QueryWords:
    def __init__(self, text):
        text = unicodedata.normalize('NFC', text)
        self.terms = {text[start:end].casefold() for start, end in _word_spans(text)}
        self.by_stem = defaultdict(list)
        for term in sorted(self.terms):
            if self._can_vary(term):
                self.by_stem[term[:-1]].append(term)
        self.forms = lru_cache(maxsize=4096)(self._forms)

    @staticmethod
    def _can_vary(word):
        return len(word) > 4 and word.isalpha()

    def _forms(self, word):
        terms = {term: False for term in self.by_stem.get(word, ())}
        if self._can_vary(word):
            stem = word[:-1]
            terms.update((term, False) for term in self.by_stem.get(stem, ()))
            if stem in self.terms:
                terms[stem] = False
        if word in self.terms:
            terms[word] = True
        return tuple(terms.items())

    def matches(self, text):
        matches = {}
        for start, end in _word_spans(text):
            for term, exact in self.forms(text[start:end].casefold()):
                if term not in matches or (exact and not matches[term].exact):
                    matches[term] = _WordMatch(exact, start, end)
        return matches


@dataclass
class _Paragraph:
    rows: list
    matches: dict


def _owners(page, anchors, lines):
    """Find the narrowest explicit anchor at each matching line."""
    regions = []
    for aid, node in anchors:
        start = node['line']
        region = anchor_region(page, start)
        if not region:
            continue
        priority = (len(region), start, aid)
        if region[-1] - region[0] + 1 == len(region):
            regions.append((region[0], region[-1], priority))
        else:
            # A table row shares its header, with other rows in between.
            regions.extend((line, line, priority) for line in region)
    regions.sort()
    active, position, owners = [], 0, {}
    for line in sorted(lines):
        while position < len(regions) and regions[position][0] <= line:
            _, end, priority = regions[position]
            if end >= line:
                heappush(active, (priority, end))
            position += 1
        while active and active[0][1] < line:
            heappop(active)
        if active:
            owners[line] = active[0][0][2]
    return owners


def _score(matches, weights):
    return (-fsum(weights[term] for term in matches),
            -fsum(weights[term] for term, exact in matches.items() if exact))


def _excerpt(rows, line, focus):
    text = ' '.join(row for _, row in rows)
    if len(text) <= EXCERPT_LENGTH:
        return text
    offset = 0
    for number, row in rows:
        if number == line:
            break
        offset += len(row) + 1
    start, end = focus.start + offset, focus.end + offset
    width = EXCERPT_LENGTH - 2
    first = min(max(0, start - width // 3), len(text) - width)
    last = first + width
    if first and text[first - 1] != ' ':
        boundary = text.find(' ', first, start)
        if boundary != -1:
            first = boundary + 1
    if last < len(text) and text[last] != ' ':
        boundary = text.rfind(' ', end, last)
        if boundary != -1:
            last = boundary
    return ('…' if first else '') + text[first:last].strip() + ('…' if last < len(text) else '')


def _evidence(matches, weights):
    return _score({term: match.exact for term, match in matches.items()}, weights)


def _best_by_target(paragraphs, owners, page_id, weights):
    best = {}
    for paragraph in paragraphs:
        grouped = defaultdict(dict)
        for line, matches in paragraph.matches.items():
            grouped[owners.get(line, page_id)][line] = matches
        for aid, evidence in grouped.items():
            combined = {}
            for matches in evidence.values():
                for term, match in matches.items():
                    combined[term] = combined.get(term, False) or match.exact
            line = min(evidence, key=lambda num: (_evidence(evidence[num], weights), num))
            key = (*_score(combined, weights), aid, line)
            if aid not in best or key < best[aid][0]:
                matches = evidence[line]
                term = min(matches, key=lambda term:
                           (-weights[term], not matches[term].exact, matches[term].start))
                best[aid] = key, paragraph.rows, matches[term]
    return best.values()


def _title(node, rows):
    if node['kind'] == 'section':
        row = rows[node['line'] - 1]
        if not HEADING.match(row):
            return node['title']
    else:
        line = node['page'].h1_line
        if not line:
            return node['title']
        row = rows[line - 1]
    return _visible_inline(_without_comments(row, False)[0])


# @trace docs/ru/slice-search.md#match
def rank_documents(index, query):
    """Return one scored excerpt per target in the selected document scope."""
    words = _QueryWords(query)
    if not words.terms:
        return []
    frequency, documents = Counter(), {}
    for path, page_id in index.page_ids.items():
        page = index.nodes[page_id]['page']
        terms, paragraphs = set(), []
        for rows in _paragraphs(page):
            evidence = {}
            for line, text in rows:
                if matches := words.matches(text):
                    terms.update(matches)
                    evidence[line] = matches
            if evidence:
                paragraphs.append(_Paragraph(rows, evidence))
        frequency.update(terms)
        if paragraphs:
            documents[path] = (page_id, paragraphs)

    # Measure how well each term narrows the pages matching the query.
    # Squared inverse odds discount common terms and cap rare ones. A half
    # page of smoothing on either side keeps every match's weight positive.
    weights = {}
    for term, count in frequency.items():
        present = (count + 0.5) ** 2
        absent = (len(documents) - count + 0.5) ** 2
        weights[term] = absent / (present + absent)
    ranked = []
    for path, (page_id, paragraphs) in documents.items():
        page = index.nodes[page_id]['page']
        lines = {line for paragraph in paragraphs for line in paragraph.matches}
        anchors = ((aid, index.nodes[aid]) for aid in index.anchors.get(path, ()))
        owners = _owners(page, anchors, lines)
        relative, page_rows = index.pr.rel(path), physical_lines(page.text)
        for key, rows, match in _best_by_target(paragraphs, owners, page_id, weights):
            aid, line = key[-2:]
            anchor = aid[len(relative) + 1:] if aid != page_id else ''
            address = document_address(relative, anchor)
            title = _title(index.nodes[aid], page_rows)
            ranked.append(((*key[:2], address, line),
                           {'target': address, 'title': title or address,
                            'excerpt': _excerpt(rows, line, match), 'line': line, 'path': path}))
    return [candidate for _, candidate in sorted(ranked, key=lambda item: item[0])]
