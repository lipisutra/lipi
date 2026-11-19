"""Общий индекс прямых подключений для среза и карты."""

import fnmatch
import re
from urllib.parse import unquote

from .i18n import tr
from .checker.conventions import CODE_EXT, K_REFINES, K_STATUS, RE_LINK
from .checker.model import anchor_region, mask_code
from .checker.targets import (
    _decision_targets, _external_path_kind, normalize_work_id, resolve_mark,
)
from .slice_index import SliceIndex, WORK_ID, anchor_title


def qualify(repo, target):
    return '%s::%s' % (repo, target) if repo is not None else target


def split_id(target):
    repo, separator, local = target.partition('::')
    return (repo, local) if separator else (None, target)


class RepoConfigError(ValueError):
    """Ошибка собственного вычисленного слоя, а не запроса к Git."""


class _LocalIndex(SliceIndex):
    def __init__(self, pr, owner, links):
        self.owner = owner
        super().__init__(pr, links=links)

    def mark(self, token):
        if '::' in token:
            return self.owner._external_mark(token)
        return super().mark(token)

    def layer(self, path):
        layer = super().layer(path)
        if '::' in layer:
            raise RepoConfigError(tr('repo.layer.reserved') % layer)
        return layer

    def resolve(self, query):
        path = self.pr.lexical_path(unquote(query.partition('#')[0]))
        if self.pr.in_connected_repo(path):
            return self._answer(query, [], 'exact')
        return super().resolve(query)


# @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
class _NeighborIndex(SliceIndex):
    """Документы только из разрешённых областей; код читается отдельным проходом."""

    def __init__(self, source, links):
        self.source = source
        self.local = None
        self.eager_documents = links
        super().__init__(source.project, links=False)
        if links and source.has_config and source.unavailable_reason is None:
            self._links()
            self._relations()

    def _documents(self):
        source, pr = self.source, self.pr
        if not source.has_config:
            return
        work_by_path = {}
        pr.mark_work_index = _decision_targets(pr) if 'decisions' in source.read else {}
        if 'decisions' in source.read:
            for did, paths in pr.mark_work_index.items():
                match = WORK_ID.fullmatch(did)
                self.work_aliases.setdefault((match[1], int(match[2])), []).append(did)
                if len(paths) == 1:
                    work_by_path[paths[0]] = did
        if not self.eager_documents:
            return
        roots, paths = [], set()
        if 'docs' in source.read:
            roots.extend(base for base in (pr.docs, pr.descr) if base)
            roots.extend(base for base in pr.editions.values() if base is not None)
            paths.add(pr.root / 'README.md')
        if 'decisions' in source.read and pr.decisions:
            roots.append(pr.decisions)
        roots = list(dict.fromkeys(roots))
        for root in roots:
            directory = pr.file_path(root, directory=True)
            if directory is None or not directory.is_dir():
                continue
            if any(other != root and other in root.parents for other in roots):
                continue
            paths.update(pr.walk_md(root, exclusions=pr.target_skip_dirs, onerror=self._walk_error))
        for path in sorted(paths):
            safe = source.resolve_path(path)
            if (safe is None or not safe.is_file()
                    or _external_path_kind(source, safe) not in source.read):
                continue
            self.add_page(safe, work_by_path.get(safe))

    def _walk_error(self, error):
        self.source.mark_unavailable(tr('repo.directory.unreadable') % error)

    def _code_walk_error(self, error):
        self._walk_error(error)

    def add_page(self, path, did=None):
        if path in self.page_ids:
            return
        page = self.pr.page(path)
        if page is None:
            self.source.mark_unavailable(tr('repo.page.encoding') % self.pr.rel(path))
            return
        rel = self.pr.rel(path)
        node = {'target': did or rel, 'title': page.h1 or rel,
                'kind': 'decision' if did else 'page', 'page': page, 'line': 1}
        if did:
            node['status'] = page.header().get(K_STATUS, '').strip('* .').lower()
            self.pr.mark_work[did] = page
        self.nodes[node['target']] = node
        self.page_ids[page.path] = node['target']
        self.anchors[page.path] = []
        duplicate = {aid for _, aid in page.dup}
        for line, anchor in page.anchor_order:
            if anchor in duplicate:
                continue
            aid = rel + '#' + anchor
            self.nodes[aid] = {'target': aid, 'title': anchor_title(page, line) or anchor,
                               'kind': 'section', 'page': page, 'line': line}
            self.anchors[page.path].append(aid)

    def _destination(self, page, link):
        relative, _, anchor = link.partition('#')
        path = self.source.resolve_path(page.path.parent / unquote(relative))
        if path not in self.page_ids:
            return None
        aid = self.pr.rel(path) + '#' + unquote(anchor) if anchor else self.page_ids[path]
        return aid if aid in self.nodes else None

    def _links(self):
        for path, page_id in self.page_ids.items():
            page = self.nodes[page_id]['page']
            regions = [(self.nodes[aid]['line'], aid,
                        set(anchor_region(page, self.nodes[aid]['line'])))
                       for aid in self.anchors[path]]
            for line, link in page.links:
                target = self._destination(page, link)
                if target is None:
                    continue
                owners = [(start, aid) for start, aid, region in regions if line in region]
                owner = page_id if self.nodes[page_id]['kind'] == 'decision' else max(
                    owners, default=(0, page_id))[1]
                self._edge(owner, target)

    def _relations(self):
        for did, node in self.nodes.items():
            if node['kind'] != 'decision':
                continue
            parents = []
            for value in node['page'].header_values(K_REFINES):
                for link in RE_LINK.finditer(mask_code(value)):
                    target = self._destination(node['page'], link[1])
                    if target in self.nodes:
                        target = self.page_ids[self.nodes[target]['page'].path]
                    if (target != did and target in self.nodes
                            and self.nodes[target]['kind'] == 'decision' and target not in parents):
                        parents.append(target)
            self.refines[did] = tuple(parents)
            for parent in parents:
                self.refinements.setdefault(parent, set()).add(did)

    def _code(self):
        # SliceIndex.__init__ вызывает этот метод до готовности своего индекса.
        if self.local is not None and self.source.has_config:
            super()._code()

    def layer(self, path):
        layer = super().layer(path)
        if '::' in layer:
            self.source.mark_unavailable(
                tr('repo.layer.reserved') % layer)
        return layer

    def _code_file_allowed(self, path, real):
        if self.source.unavailable_reason is not None:
            return False
        for candidate in {path, real}:
            layer = self.layer(self.pr.rel(candidate))
            test = layer == 'tests' or any(fnmatch.fnmatchcase(candidate.name, pattern)
                                          for pattern in self.pr.cfg['tests'])
            if ('tests' if test else 'code') not in self.source.read:
                return False
        return True

    def _read_code(self, path):
        try:
            return path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            if re.search(r'\.(?:%s)$' % CODE_EXT, path.name, re.I):
                self.source.mark_unavailable(tr('repo.file.encoding') % self.pr.rel(path))
        except OSError as error:
            self.source.mark_unavailable(tr('repo.file.unreadable') % (self.pr.rel(path), error))
        return None

    def mark(self, token):
        alias, separator, target = token.partition('::')
        if separator and self.source.points_to_local(alias):
            # Только обратная ссылка; локальный индекс не должен снова открыть соседа.
            if '::' not in target:
                return self.local.mark(target)
        return None


# @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
class RepoIndex:
    """SliceIndex-совместимые таблицы с квалифицированными внутренними ID.

    node.target и ключи таблиц включают имя источника. path/layer места
    остаются локальными, repo различает физические места. Подиндексы indices
    сохраняют локальные ID; внешние метки своего кода уже квалифицированы.
    """

    def __init__(self, pr, *, links=True):
        self.pr, self.sources = pr, pr.sources
        self.indices = {}
        self._neighbors = {}
        for source in self.sources.all:
            if source.name is not None and source.state != 'unavailable':
                self._neighbors[source.name] = _NeighborIndex(source, links)
        self.local = _LocalIndex(pr, self, links)
        for index in self._neighbors.values():
            if index.source.unavailable_reason is None and any(
                    capability in index.source.read for capability in ('code', 'tests')):
                index.local = self.local
                index._code()
        self.layer_order = self.local.layer_order
        self.work_aliases = self.local.work_aliases
        self.prune_unavailable()

    def _external_mark(self, token):
        repo, _ = split_id(token)
        index = self._neighbors.get(repo)
        if index is None or index.source.state == 'unavailable':
            return None
        aid, _ = resolve_mark(self.pr, token)
        if aid is None:
            return None
        repo, local = split_id(aid)
        if local not in index.nodes:
            metadata = self.pr.mark_external[aid]
            page = (self.pr.mark_work[aid] if aid in self.pr.mark_work
                    else self.pr.mark_anchors[aid][0])
            index.add_page(page.path, metadata.get('decision'))
        return aid if local in index.nodes else None

    def mark(self, token, repo=None):
        if repo is not None:
            source = self.sources.get(repo)
            if source is None or source.state == 'unavailable':
                return None
            alias, separator, local = token.partition('::')
            if separator:
                return self.local.mark(local) if source.points_to_local(alias) and '::' not in local else None
            token = qualify(repo, token)
        result = self._external_mark(token) if '::' in token else self.local.mark(token)
        self.prune_unavailable()
        return result if result in self.nodes else None

    def prune_unavailable(self):
        """Собирает таблицы заново: частично прочитанный сосед не даёт данных."""
        self.indices = {None: self.local}
        self.indices.update((name, index) for name, index in self._neighbors.items()
                            if index.source.state != 'unavailable')
        self.nodes, self.page_ids, self.anchors = {}, {}, {}
        self.outgoing, self.incoming, self.refines, self.refinements = {}, {}, {}, {}
        self.places, self.by_target, self.by_file, self.boundaries = [], {}, {}, {}
        for repo, index in self.indices.items():
            for aid, node in index.nodes.items():
                key = qualify(repo, aid)
                self.nodes[key] = dict(node, target=key, repo=repo)
                if repo is not None and node['kind'] == 'decision':
                    self.pr.mark_work[key] = node['page']
                    self.pr.mark_external[key] = {
                        'source': index.source, 'target': aid, 'decision': aid}
            self.page_ids.update((path, qualify(repo, aid)) for path, aid in index.page_ids.items())
            self.anchors.update((path, [qualify(repo, aid) for aid in ids])
                                for path, ids in index.anchors.items())
            for attribute in ('outgoing', 'incoming', 'refines', 'refinements'):
                destination = getattr(self, attribute)
                destination.update((qualify(repo, aid), {qualify(repo, item) for item in ids})
                                   for aid, ids in getattr(index, attribute).items())
            self.boundaries.update((qualify(repo, path), lines) for path, lines in index.boundaries.items())
        for repo, index in self.indices.items():
            for original in index.places:
                # У соседей targets — обратные локальные ID; у своего есть и внешние ID.
                targets = {aid: line for aid, line in original['targets'].items() if aid in self.nodes}
                if not targets:
                    continue
                place = dict(original, targets=targets, repo=repo)
                self.places.append(place)
                self.by_file.setdefault(qualify(repo, place['path']), []).append(place)
                for aid in targets:
                    self.by_target.setdefault(aid, []).append(place)
        self.local_marked = frozenset(aid for place in self.places if place['repo'] is None
                                      for aid in place['targets'])
        self.local_explicit_decisions = {aid for aid in self.local_marked
                                         if self.nodes[aid]['kind'] == 'decision'}

    def place_order(self, place):
        repo = place.get('repo')
        order = list(self.indices).index(repo)
        return (order, *self.indices[repo].place_order(place))

    def layer(self, path):
        return self.local.layer(path)

    def count(self, target):
        targets = {target}
        node = self.nodes.get(target)
        if node and node['kind'] == 'page':
            targets.update(self.anchors[node['page'].path])
        return len({(place['repo'], place['path'], place['line']) for aid in targets
                    for place in self.by_target.get(aid, []) if not place['test']})

    def checks_repos(self):
        records = [{'repo': source.name, 'state': source.state, 'head': source.head,
                    'dirty': source.dirty, 'reason': source.reason, 'read': list(source.read)}
                   for source in self.sources.all]
        self.prune_unavailable()
        return records

    def resolve(self, query):
        repo, local = split_id(query)
        if repo is None:
            node, error = self.local.resolve(query)
            self.prune_unavailable()
            return (dict(node, repo=None) if node else None), error
        source = self.sources.get(repo)
        error = {'schema': 1, 'error': 'not-found', 'query': query, 'candidates': []}
        if source is None:
            return None, dict(error, message=tr('repo.target.unknown_repo') % repo)
        if source.state == 'unavailable':
            did = normalize_work_id(local)
            kind = 'decision' if did and did.startswith('ADR-') else (
                'section' if '#' in local else 'page' if local.lower().endswith('.md') else None)
            return {'target': query, 'repo': repo, 'title': '', 'kind': kind, 'unavailable': True}, None
        index = self._neighbors[repo]
        if not source.has_config and '#' not in local:
            return None, dict(error, message=tr('repo.target.no_config'))
        if '#' in local or WORK_ID.fullmatch(local):
            aid = self.mark(query)
            if source.state == 'unavailable':
                return self.resolve(query)
            if aid:
                return dict(self.nodes[aid], found='exact'), None
            # Поиск по номеру должен сохранить неоднозначные пути кандидатов.
            if not WORK_ID.fullmatch(local):
                return None, dict(error, message=tr('repo.target.unavailable'))
        # Base resolve не читает страницу вне page_ids, но проверяет путь:
        # сначала удерживаем его внутри источника и запрещаем внешние файлы кода.
        if '/' in local or local.lower().endswith('.md'):
            path = source.resolve_path(unquote(local))
            if path is None or path not in index.page_ids:
                return None, dict(error, message=tr('repo.target.unavailable'))
        node, result_error = SliceIndex.resolve(index, local)
        if node is not None and node['kind'] == 'code':
            return None, dict(error, message=tr('repo.target.foreign_code'))
        if result_error:
            result_error = dict(result_error, query=query)
            if result_error['error'] == 'not-found':
                result_error.setdefault('message', tr('repo.target.unavailable'))
            result_error['candidates'] = [dict(item, repo=repo) for item in result_error['candidates']]
            return None, result_error
        target = qualify(repo, node['target'])
        result = dict(node, target=target, repo=repo)
        if '_work_id' in result:
            result['_work_id'] = qualify(repo, result['_work_id'])
        self.prune_unavailable()
        return result, None
