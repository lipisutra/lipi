"""Общие метаданные и сигналы подключений для среза и карты."""

from .i18n import tr
from .checker.report import CODE_LEVELS


# @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
def repository_status(pr):
    records = [{"repo": source.name, "state": source.state, "head": source.head,
                "dirty": source.dirty, "reason": source.reason, "read": list(source.read)}
               for source in pr.sources.all]
    available = [item["repo"] or tr('repo.label.local') for item in records if item["state"] != "unavailable"]
    notes = [{"code": "repos-scope", "text":
              tr('repo.note.scope') % ", ".join(available)}]
    signals = []
    level = pr.cfg.get("codes", {}).get("T4", CODE_LEVELS["T4"])
    for item in records:
        name = item["repo"] or tr('repo.label.local')
        if item["state"] == "unavailable":
            message = tr('repo.signal.unavailable') % (name, item["reason"])
            notes.append({"code": "repos-incomplete", "text":
                          tr('repo.note.incomplete') % (name, item["reason"])})
            if level != "off":
                signals.append({"repo": item["repo"], "target_repo": item["repo"],
                                "code": "T4", "level": level, "message": message,
                                "target": item["repo"] or tr('repo.label.local')})
        elif item["state"] != "ok" or item["head"] is None or item["dirty"] is not False:
            reasons = []
            if item["state"] == "no-git":
                reasons.append(tr('repo.state.no_git'))
            elif item["head"] is None:
                reasons.append(tr('repo.state.no_head'))
            if item["dirty"] is True:
                reasons.append(tr('repo.state.dirty'))
            elif item["dirty"] is None and item["state"] != "no-git":
                reasons.append(tr('repo.state.unknown'))
            notes.append({"code": "repos-unreproducible", "text":
                          tr('repo.note.unreproducible') % (name, ", ".join(reasons))})
    return {"checks": {"repos": records},
            "reproducible": all(item["state"] == "ok" and item["head"] is not None
                                and item["dirty"] is False for item in records),
            "incomplete": any(item["state"] == "unavailable" for item in records),
            "notes": notes, "signals": signals}


# @trace docs/ru/slice.md#repos,docs/ru/map.md#repos
def render_repository_status(response):
    records = response.get("checks", {}).get("repos")
    if records is None:
        return []
    descriptions = []
    for item in records:
        name = item["repo"] or tr('repo.label.local')
        if item["state"] == "unavailable":
            descriptions.append(name + tr('repo.render.unavailable'))
        elif item["state"] == "no-git":
            descriptions.append(name + tr('repo.render.no_git'))
        else:
            head = item["head"][:7] if item["head"] else tr('repo.state.no_head')
            state = (tr('repo.state.dirty') if item["dirty"] is True else tr('repo.render.clean')
                     if item["dirty"] is False else tr('repo.render.unknown'))
            descriptions.append("%s %s, %s" % (name, head, state))
    return [tr('repo.render.sources') + "; ".join(descriptions)]
