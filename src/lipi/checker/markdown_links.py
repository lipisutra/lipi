"""Link destinations in Markdown, with offsets into the original source."""

import html
import re
from dataclasses import dataclass
from typing import Optional


def _blank(text):
    return ''.join('\n' if char == '\n' else ' ' for char in text)


def mask_examples(text):
    """Маска примеров сохраняет каждый offset, включая строки внутри fences."""
    rows, fence = [], None
    list_indents, previous_blank, code_block = [], True, False
    for row in text.splitlines(keepends=True):
        indent = len(row.expandtabs(4)) - len(row.expandtabs(4).lstrip(' '))
        if row.strip():
            while list_indents and indent < list_indents[-1]:
                list_indents.pop()
        base = list_indents[-1] if list_indents else 0
        indented = indent >= base + 4 and (previous_blank or code_block)
        marker = re.match(r'^[ \t]*(`{3,}|~{3,})(.*)', row)
        if fence:
            rows.append(_blank(row))
            if (marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence)
                    and not marker[2].strip()):
                fence = None
        elif indented:
            rows.append(_blank(row))
            code_block = True
        elif marker:
            fence = marker[1]
            rows.append(_blank(row))
        else:
            rows.append(row)
            if row.strip():
                code_block = False
                item = re.match(r'^[ \t]*(?:[-+*]|\d+[.)])[ \t]+', row)
                if item:
                    list_indents.append(len(item[0].expandtabs(4)))
        previous_blank = not row.strip()
    masked = ''.join(rows)
    return re.sub(r'(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)',
                  lambda match: _blank(match[0]), masked)


def _destination(text, start):
    """Границы адреса без <>, скобок ссылки и необязательного title."""
    pos, size = start, len(text)
    while pos < size and text[pos].isspace():
        pos += 1
    if pos == size:
        return None
    if text[pos] == '<':
        end = pos + 1
        while end < size and text[end] not in '>\n':
            end += 2 if text[end] == '\\' else 1
        return (pos + 1, end) if end < size and text[end] == '>' else None
    start, depth = pos, 0
    while pos < size:
        char = text[pos]
        if char == '\\':
            pos += 2
            continue
        if char.isspace() or (char == ')' and depth == 0):
            break
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        pos += 1
    return (start, pos) if pos > start and depth == 0 else None


def _link_spans(masked):
    # Links/images share the same destination syntax; labels stay untouched.
    pos, brackets = 0, []
    while pos < len(masked):
        if masked[pos] == '\\':
            pos += 2
            continue
        if masked[pos] == '[':
            brackets.append(pos)
        elif masked[pos] == ']' and brackets:
            brackets.pop()
            span = _destination(masked, pos + 2) if masked[pos:pos + 2] == '](' else None
            if span:
                end = span[1] + (masked[span[1]:span[1] + 1] == '>')
                # A destination without a closing link is plain text, not a link.
                tail = re.match(r'''\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))?\s*\)''',
                                masked[end:])
                if tail:
                    yield span
                    pos = end + tail.end()
                    continue
        pos += 1
    for match in re.finditer(r'^ {0,3}\[[^\]\n]+\]:[ \t]*', masked, re.M):
        span = _destination(masked, match.end())
        if span:
            yield span



@dataclass(frozen=True)
class Link:
    start: int
    end: int
    address: str
    attribute_quote: Optional[str] = None

    def encode(self, address):
        if self.attribute_quote is not None:
            # Also valid in an unquoted attribute.
            encoded = html.escape(address, quote=True)
            if not self.attribute_quote:
                encoded = encoded.replace('=', '&#61;').replace(chr(96), '&#96;')
            return encoded
        return address


# Consume whole tags so src/href text inside another attribute is ignored.
_NAME = r'''[^\s"'<>/=\x00-\x1f]+'''
_VALUE = r'''"[^"]*"|'[^']*'|[^\s"'=<>`]+'''
_ATTR = rf'''\s+({_NAME})(?:\s*=\s*({_VALUE}))?'''
_TAG = re.compile(rf'''<!--.*?(?:-->|\Z)|<([a-zA-Z][a-zA-Z0-9:-]*)(?:{_ATTR})*\s*/?>''', re.S)
_ATTRIBUTE = re.compile(_ATTR)


def links_in_mask(masked, source):
    """Yield HTML and Markdown destinations in source order; offsets refer to source."""
    links, chunks, cursor = [], [], 0
    for tag in _TAG.finditer(masked):
        name = tag[1]
        if name:
            if masked[tag.start() - 1:tag.start()] == '\\':
                continue
            if not tag[2]:
                continue
            # An angle-delimited Markdown destination may itself look like a tag.
            prefix = masked[masked.rfind('\n', 0, tag.start()) + 1:tag.start()].rstrip()
            if prefix.endswith('](') or re.fullmatch(r' {0,3}\[[^\]]+\]:', prefix):
                continue
            wanted = {'img': 'src', 'a': 'href'}.get(name.lower())
            for attr in _ATTRIBUTE.finditer(tag[0], 1 + len(name)):
                if attr[1].lower() != wanted or not attr[2]:
                    continue
                start = tag.start() + attr.start(2)
                end = tag.start() + attr.end(2)
                quote_char = attr[2][0] if attr[2][0] in ('"', "'") else ''
                if quote_char:
                    start += 1
                    end -= 1
                links.append(Link(start, end, html.unescape(source[start:end]), quote_char))
                break
        chunks.extend((masked[cursor:tag.start()], _blank(tag[0])))
        cursor = tag.end()
    if chunks:
        masked = ''.join(chunks) + masked[cursor:]
    links.extend(Link(start, end, source[start:end]) for start, end in _link_spans(masked))
    return sorted(links, key=lambda link: link.start)


def markdown_links(text):
    if '[' not in text and '<' not in text:
        return []
    return links_in_mask(mask_examples(text), text)
