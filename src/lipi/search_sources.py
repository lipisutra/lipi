"""Document search in the local project or one direct connection."""

from os.path import relpath

from .i18n import tr
from .repo_index import _NeighborIndex, split_id
from .search_match import rank_documents
from .slice_index import SliceIndex


def _editor_path(path, cwd):
    try:
        return relpath(path, cwd)
    except ValueError:
        # Relpaths across drives are unavailable on Windows.
        return str(path)


def _incomplete(response, repo, reason):
    name = repo or tr('repo.label.local')
    message = '%s%s (%s)' % (name, tr('repo.render.unavailable'), reason)
    return dict(response, incomplete=True, message=message), 0


# @trace docs/ru/slice-search.md#scope,docs/ru/slice-search.md#output
def search_documents(project, query, cwd):
    repo, phrase = split_id(query)
    response = {'schema': 1, 'query': query, 'candidates': [], 'total': 0}
    miss = dict(response, error='not-found')
    source = project.sources.get(repo)
    if source is None:
        return dict(miss, message=tr('repo.target.unknown_repo') % repo), 1
    if repo is not None:
        if source.state == 'unavailable':
            return _incomplete(response, repo, source.reason)
        if not source.has_config:
            return dict(miss, reason='no-config', message=tr('repo.target.no_config')), 1
        if not {'docs', 'decisions'}.intersection(source.read):
            return dict(miss, reason='scope-not-enabled',
                        message=tr('repo.target.scope_not_enabled') % ('docs', repo)), 1
    try:
        index = (SliceIndex(project, documents_only=True) if repo is None
                 else _NeighborIndex(source, links=False, documents_only=True))
    except OSError as error:
        return _incomplete(response, repo, tr('repo.directory.unreadable') % error)
    unreadable = index.document_error or source.unavailable_reason
    if unreadable is not None:
        return _incomplete(response, repo, unreadable)

    matches = rank_documents(index, phrase)
    if not matches:
        return miss, 1
    candidates = [
        {'repo': repo, 'target': match['target'], 'title': match['title'],
         'excerpt': match['excerpt'], 'file': _editor_path(match['path'], cwd),
         'line': match['line']}
        for match in matches[:5]
    ]
    return dict(response, candidates=candidates, total=len(matches)), 0
