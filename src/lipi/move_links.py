"""Точные замены адресов для mv без переформатирования исходного текста."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Mapping, Tuple
from urllib.parse import quote, unquote

from .checker.markdown_links import links_in_mask, mask_examples
from .checker.marks import ignores_trace


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    before: str
    after: str


def _comments(text, path):
    """Небольшой лексер комментариев; строки, в том числе triple/backtick, закрыты.

    Для Python достаточно #; остальные языки допускают распространённые
    #, //, /* */, -- и ; в начале строки. Это не парсер грамматики языка.
    """
    python = path.suffix.lower() in {'.py', '.pyi', '.pyw'}
    pos, size = 0, len(text)
    while pos < size:
        char = text[pos]
        if char in "\"'`":
            delimiter = char * 3 if text.startswith(char * 3, pos) else char
            pos += len(delimiter)
            while pos < size:
                if not python and len(delimiter) == 1 and delimiter != '`' and text[pos] == '\n':
                    break
                if text[pos] == '\\':
                    pos += 2
                elif text.startswith(delimiter, pos):
                    pos += len(delimiter)
                    break
                else:
                    pos += 1
            continue
        if not python and text.startswith('/*', pos):
            end = text.find('*/', pos + 2)
            end = size if end < 0 else end
            yield pos + 2, end
            pos = end + 2
            continue
        line_comment = char == '#'
        if not python:
            line_comment = (line_comment or text.startswith('//', pos)
                            or text.startswith('--', pos)
                            or (char == ';' and not text[text.rfind('\n', 0, pos) + 1:pos].strip()))
        if line_comment:
            end = text.find('\n', pos)
            end = size if end < 0 else end
            yield pos, end
            pos = end
        else:
            pos += 1


_TRACE = re.compile(r'@trace[ \t]+([^\s,]+(?:[ \t]*,[ \t]*[^\s,]+)*)')


# @trace docs/ru/move.md#links
def trace_targets(text: str, path: Path) -> Iterator[Tuple[int, str]]:
    """Адрес и его offset только внутри комментария, для mv и отчёта соседей."""
    for start, end in _comments(text, Path(path)):
        for marker in _TRACE.finditer(text, start, end):
            line_start = text.rfind('\n', 0, marker.start()) + 1
            line_end = text.find('\n', marker.end())
            if ignores_trace(text[line_start:line_end if line_end >= 0 else len(text)]):
                continue
            for token in re.finditer(r'[^\s,]+', marker[1]):
                yield marker.start(1) + token.start(), token[0]


def _absolute(path, root):
    return Path(os.path.abspath(root / path))


def _address(value, *, base, after_base, moves, root, target_allowed=None):
    # Schemes also exclude neighbour aliases (alias::path). Local anchors
    # belong to the moving page, so do not acquire a filename.
    if not value or value.startswith(('#', '?', '//')) or re.match(r'^[\w+.-]+:', value):
        return value
    match = re.match(r'([^?#]*)([?#].*)?$', value, re.S)
    address, suffix = match[1], match[2] or ''
    decoded = unquote(re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]^_`{|}~])', r'\1', address))
    rooted = decoded.startswith('/')
    target = _absolute(decoded.lstrip('/') if rooted else decoded, root if rooted else base)
    after_target = moves.get(target, target)
    if rooted:
        if after_target == target:
            return value
        rewritten = '/' + after_target.relative_to(root).as_posix()
    else:
        before_relative = os.path.relpath(target, base)
        after_relative = os.path.relpath(after_target, after_base)
        # Moving both ends together preserves the original URL byte for byte,
        # including redundant ./ segments, escapes and percent-encoded letters.
        if before_relative == after_relative:
            return value
        if after_target == target and target_allowed is not None and not target_allowed(target):
            return value
        rewritten = Path(after_relative).as_posix()
    if address.startswith('./') and not rewritten.startswith(('.', '/')):
        rewritten = './' + rewritten
    if re.search(r'%[0-9a-fA-F]{2}', address):
        rewritten = quote(rewritten, safe="/!$&'*+,-.:;=@_~")
    elif '\\' in address:
        rewritten = re.sub(r'([ ()])', r'\\\1', rewritten)
    else:
        # New filenames may require escaping even when the old one did not.
        rewritten = re.sub(r'[%\s?#<>()]', lambda match: quote(match[0], safe=''), rewritten)
    return rewritten + suffix


# @trace docs/ru/move.md#links,ADR-017
def replacements(text: str, *, path: Path, moves: Mapping[Path, Path],
                 root: Path, markdown: bool, target_allowed=None) -> List[Replacement]:
    """Замены с offsets в исходном text; пути и таблицу нормализует вызывающий.

    root, path и обе стороны moves — абсолютные пути. Таблица общая для
    всех файлов проекта, здесь не копируется и не меняется.
    """
    after_path = moves.get(path, path)
    found = {}

    def add(start, end, marker=False, link=None):
        before = text[start:end]
        value = link.address if link else before
        after = _address(value, base=root if marker else path.parent,
                         after_base=root if marker else after_path.parent,
                         moves=moves, root=root, target_allowed=target_allowed)
        if value != after:
            if link:
                after = link.encode(after)
            found[(start, end)] = Replacement(start, end, before, after)

    if markdown:
        masked = mask_examples(text)
        for comment in re.finditer(r'<!--[\s\S]*?-->', masked):
            cover = re.match(r'<!--\s*covers:\s*([\s\S]*?)\s*-->', comment[0])
            if cover:
                for token in re.finditer(r'[^\s,]+', cover[1]):
                    start = comment.start() + cover.start(1) + token.start()
                    add(start, start + len(token[0]), marker=True)
        for link in links_in_mask(masked, text):
            add(link.start, link.end, link=link)
    else:
        for start, token in trace_targets(text, path):
            add(start, start + len(token), marker=True)
    result = []
    for change in sorted(found.values(), key=lambda item: (item.start, -item.end)):
        if not result or change.start >= result[-1].end:
            result.append(change)
    return result
