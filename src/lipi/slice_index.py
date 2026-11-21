"""Читаемый индекс целей, явных ссылок и блоков меток для среза."""

import re
from pathlib import Path
from urllib.parse import unquote

from .i18n import tr
from .checker.config import code_layer, is_configured_test_file
from .checker.conventions import K_STATUS, MAX_CODE_FILE
from .checker.marks import physical_lines, standalone_trace, trace_groups
from .checker.model import anchor_region, read_text, resolve_target
from .checker.targets import decision_relations, resolve_mark, target_excluded, work_targets

WORK_ID = re.compile(r"^(ADR|ISS|PLN|DSC|AUD)-(\d+)$", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def clean_title(text):
    literals = []
    def literal(match):
        literals.append(match[2] if match[1] else match[3])
        return '\0%d\0' % (len(literals) - 1)
    text = re.sub(r"(`+)(.+?)\1|\\([\\`*_{}\[\]()#+.!|>~-])", literal, text)
    text = re.sub(r"<[^>]+>", "", text)
    if HEADING.match(text):
        text = re.sub(r"^#{1,6}\s+", "", text)
        text = re.sub(r"\s+#+\s*$", "", text)
    text = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"!?\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"^\s*(?:[-+*]|\d+[.)])\s+", "", text)
    text = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w\\])([*_])(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", text)
    text = re.sub('\0(\\d+)\0', lambda match: literals[int(match[1])], text)
    return ' '.join(text.split())


def anchor_title(page, line):
    """Имя принадлежит самому элементу с якорем, а не предыдущему разделу."""
    rows = physical_lines(page.text)
    raw = rows[line - 1]
    if HEADING.match(physical_lines(page.masked)[line - 1]):
        return clean_title(raw)
    if raw.lstrip().startswith('|'):
        cell = re.split(r'(?<!\\)\|', raw.lstrip()[1:], maxsplit=1)[0]
        return clean_title(cell)
    title = clean_title(' '.join(rows[num - 1] for num in anchor_region(page, line)))
    if len(title) > 80:
        prefix = title[:79]
        if not title[79].isspace() and not prefix[-1].isspace():
            prefix = prefix.rsplit(' ', 1)[0]
        title = prefix.rstrip() + '…'
    return title


def target_order(target):
    match = WORK_ID.fullmatch(target)
    return (0, match[1].upper(), int(match[2])) if match else (1, target, 0)


def document_order(target):
    match = WORK_ID.fullmatch(target)
    if match and match[1].upper() == 'ADR':
        return (0, int(match[2]), '')
    return (1, 0, target)


def declaration_line(rows, group):
    if not group['standalone']:
        return group['start']
    return next((line for line in range(group['end'] + 1, group['region_end'] + 1)
                 if rows[line - 1].strip() and not rows[line - 1].lstrip().startswith(
                     ('#', '//', '/*', '*', '--', ';', '<!--'))), None)


class SliceIndex:
    def __init__(self, pr, *, links=True):
        self.pr = pr
        self.nodes = {}
        self.page_ids = {}
        self.anchors = {}
        self.outgoing = {}
        self.incoming = {}
        self.places = []
        self.by_target = {}
        self.by_file = {}
        self.boundaries = {}
        self.code_texts = {}
        self.work_aliases = {}
        self._marks = {}
        self.layer_order = list(dict.fromkeys(pr.cfg.get('layers', {}).values()))
        self.entry = [re.compile(pattern) for pattern in pr.cfg.get('entry', [])]
        self._documents()
        self.refines = {}
        self.refinements = {}
        if links:
            self._links()
            self.refines = {child: tuple(parent for parent in parents if parent in self.nodes)
                            for child, parents in decision_relations(pr).items()
                            if child in self.nodes}
            for child, parents in self.refines.items():
                for parent in parents:
                    self.refinements.setdefault(parent, set()).add(child)
        self._code()

    def layer(self, path):
        return code_layer(path, self.pr.cfg)

    def place_order(self, place):
        layer = place['layer']
        rank = self.layer_order.index(layer) if layer in self.layer_order else len(self.layer_order)
        return rank, layer, place['path'], place['line']

    def _documents(self):
        pr = self.pr
        work_by_path = {}
        for did, paths in work_targets(pr).items():
            match = WORK_ID.fullmatch(did)
            self.work_aliases.setdefault((match[1].upper(), int(match[2])), []).append(did)
            if len(paths) == 1:
                work_by_path[paths[0]] = did
        for real in pr.walk_md(pr.root, exclusions=pr.target_skip_dirs, resolved=True,
                               path_filter=lambda path: not target_excluded(pr, path)):
            if target_excluded(pr, real) or real in self.page_ids:
                continue
            page = pr.page(real)
            if page is None:
                continue
            rel = pr.rel(real)
            did = work_by_path.get(real)
            kind = ('decision' if did.startswith('ADR-') else 'work') if did else 'page'
            node = {'target': did or rel, 'title': page.h1 or rel, 'kind': kind,
                    'page': page, 'line': 1}
            if did:
                node['status'] = page.header().get(K_STATUS, '').strip('* .').lower()
                pr.mark_work[did] = page
            self.nodes[node['target']] = node
            self.page_ids[page.path] = node['target']
            self.anchors[page.path] = []
            duplicate = {aid for _, aid in page.dup}
            for line, anchor in page.anchor_order:
                if anchor in duplicate:
                    continue
                aid, error = resolve_mark(pr, rel + '#' + anchor)
                if error:
                    continue
                title = anchor_title(page, line)
                if not title:
                    title = anchor
                self.nodes[aid] = {'target': aid, 'title': title, 'kind': 'section',
                                   'page': page, 'line': line}
                self.anchors[page.path].append(aid)

    def mark(self, token):
        if token not in self._marks:
            original = token
            match = WORK_ID.fullmatch(token)
            if match:
                aliases = self.work_aliases.get((match[1].upper(), int(match[2])), [])
                token = aliases[0] if len(aliases) == 1 else token
            resolved, _ = resolve_mark(self.pr, token)
            self._marks[original] = resolved if resolved in self.nodes else None
            return self._marks[original]
        return self._marks[token]

    def _edge(self, source, target):
        if source != target:
            self.outgoing.setdefault(source, set()).add(target)
            self.incoming.setdefault(target, set()).add(source)

    def _links(self):
        for path, page_id in self.page_ids.items():
            page = self.nodes[page_id]['page']
            regions = []
            for aid in self.anchors[path]:
                region = anchor_region(page, self.nodes[aid]['line'])
                if region:
                    regions.append((self.nodes[aid]['line'], aid, set(region)))
            for line, link in page.links:
                dest, anchor = resolve_target(page, link, self.pr)
                if dest not in self.page_ids:
                    continue
                target = self.pr.rel(dest) + '#' + anchor if anchor else self.page_ids[dest]
                if target not in self.nodes:
                    continue
                owners = [(start, aid) for start, aid, region in regions if line in region]
                source = max(owners, default=(0, page_id))[1]
                if self.nodes[page_id]['kind'] in ('work', 'decision'):
                    source = page_id
                self._edge(source, target)

    @staticmethod
    def _standalone(line):
        return standalone_trace(line)

    def _code_file_allowed(self, path, real):
        source = self.pr.sources.local
        return source._path_allowed(path) and (path == real or source._path_allowed(real))

    def _read_code(self, path):
        return read_text(path)

    def _code_walk_error(self, error):
        pass

    def code_place(self, path, rows, group):
        line = declaration_line(rows, group)
        declaration = rows[line - 1] if line is not None else ''
        layer = self.layer(path)
        return {'path': path, 'line': group['start'], 'symbol': declaration.strip()[:80],
                'layer': layer, 'targets': group['targets'], 'target_roles': group['target_roles'],
                'history_line': group['end'],
                'end_line': group['end'], 'region_end': group['region_end'],
                'test': is_configured_test_file(path, layer, self.pr.cfg),
                'entry': any(pattern.search(declaration) for pattern in self.entry)}

    def _code(self):
        pr = self.pr
        skip_paths = {path for path in (pr.docs, pr.wf, pr.decisions)
                      if path and path != pr.root}
        for candidate, path in pr._walk_selected(
                skip=skip_paths, onerror=self._code_walk_error,
                path_filter=lambda path: path.suffix.lower() != '.md'):
            if path.suffix.lower() == '.md' or not self._code_file_allowed(candidate, path):
                continue
            try:
                if path.stat().st_size > MAX_CODE_FILE:
                    continue
            except OSError:
                continue
            text = self._read_code(path)
            if text is None or '@trace' not in text:
                continue
            rel, rows = pr.rel(path), physical_lines(text)
            self.code_texts[rel] = text
            groups = trace_groups(rows, self.mark)
            self.boundaries[rel] = [group['start'] for group in groups]
            for group in groups:
                if not group['targets']:
                    continue
                place = self.code_place(rel, rows, group)
                self.places.append(place)
                self.by_file.setdefault(rel, []).append(place)
                for aid in group['targets']:
                    self.by_target.setdefault(aid, []).append(place)

    def resolve(self, query):
        """Одна цель или фиксированный список кандидатов; файловые формы точны."""
        match = WORK_ID.fullmatch(query)
        if match:
            aliases = self.work_aliases.get((match[1].upper(), int(match[2])), [])
            matches = []
            for did in aliases:
                if did in self.nodes:
                    matches.append(self.nodes[did])
                else:
                    # У неоднозначного номера кандидаты — различимые пути.
                    for work_path in work_targets(self.pr).get(did, []):
                        page_id = self.page_ids.get(work_path)
                        if page_id in self.nodes:
                            matches.append(self.nodes[page_id])
            return self._answer(query, matches, 'exact')
        if '#' in query:
            aid = self.mark(query)
            return self._answer(query, [self.nodes[aid]] if aid else [], 'exact')
        relative = Path(unquote(query))
        lexical = self.pr.lexical_path(relative)
        path = (self.pr.file_path(lexical)
                if not relative.is_absolute() and not target_excluded(self.pr, lexical) else None)
        if path is not None and not target_excluded(self.pr, path) and path.is_file():
            if path.suffix.lower() == '.md':
                aid = self.page_ids.get(path)
                if aid:
                    node = self.nodes[aid]
                    page_target = {'target': self.pr.rel(path), 'title': node['title'],
                                   'kind': 'page', 'page': node['page'], 'line': 1}
                    if node['kind'] in ('work', 'decision'):
                        page_target['_work_id'] = aid
                    return self._answer(query, [page_target], 'exact')
                return self._answer(query, [], 'exact')
            rel = self.pr.rel(path)
            return {'target': rel, 'title': tr('slice.code.title'), 'kind': 'code',
                    'layer': self.layer(rel), 'found': 'exact'}, None
        if '/' in query or query.lower().endswith('.md'):
            return self._answer(query, [], 'exact')
        needle = query.casefold()
        candidates = self._search_candidates()
        def name(node):
            return node['target'].partition('#')[2] if node['kind'] == 'section' else (
                node['target'] if node['kind'] in ('work', 'decision') else '')
        for found, predicate in (
            ('anchor', lambda node: name(node).casefold() == needle),
            ('substring', lambda node: needle in name(node).casefold()),
            ('title', lambda node: needle in node['title'].casefold()),
        ):
            matches = [node for node in candidates if name(node) or found == 'title' if predicate(node)]
            if matches:
                return self._answer(query, matches, found)
        return self._answer(query, [], 'title')

    def _search_candidates(self):
        return [node for node in self.nodes.values()
                if node['kind'] != 'page' or not any(
                    self.nodes[anchor]['title'] == node['title']
                    for anchor in self.anchors[node['page'].path])]

    def _answer(self, query, matches, found):
        matches = sorted(matches, key=lambda node: target_order(node['target']))
        if len(matches) == 1:
            return dict(matches[0], found=found), None
        if len(matches) > 1 and found != 'title':
            matched = {node['target'] for node in matches}
            matches += sorted((node for node in self._search_candidates()
                               if node['target'] not in matched
                               and query.casefold() in node['title'].casefold()),
                              key=lambda node: target_order(node['target']))
        return None, {'schema': 1, 'error': 'ambiguous' if matches else 'not-found',
                      'query': query, 'candidates': [
                          {'target': node['target'], 'title': node['title']} for node in matches[:5]]}

    def count(self, target):
        targets = {target}
        node = self.nodes.get(target)
        if node and node['kind'] == 'page':
            targets.update(self.anchors[node['page'].path])
        return len({(place['path'], place['line']) for aid in targets
                    for place in self.by_target.get(aid, []) if not place['test']})
