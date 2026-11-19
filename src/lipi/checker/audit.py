"""Аудит рабочих материалов и связи кода с описанием."""

import datetime
import os
import re
import subprocess

from lipi.i18n import tr
from .conventions import (
    BASE_NAME, CODE_EXT, FINAL, K_DUE, K_UPDATED, RE_DATE, RE_DOC_REF,
    STATUSES,
)
from .history import GitBlame
from .marks import physical_lines, trace_matches
from .model import is_test_file, read_text, resolve_target
from .reviews import REVIEWS_NAME, ReviewContext, ReviewError, parse_reviews
from .state import read_baseline


# @trace docs/ru/review.md#authors
def review_base(root, revision):
    """Возвращает ревизию, полный OID и ID записей из реестра в коммите."""
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=True,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0")).stdout

    single_commit = tr("checker.audit.commit_unresolved") % revision
    try:
        verify = ("rev-parse", "--verify", "--end-of-options")
        oid = git(*verify, revision).decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise ValueError(single_commit)
        # Для REV:path добавленный напрямую суффикс считался бы частью пути.
        commit = git(*verify, oid + "^{commit}").decode("ascii").strip()
    except OSError as error:
        raise ValueError(tr("checker.audit.git_unavailable") % error) from error
    except subprocess.CalledProcessError as error:
        raise ValueError(single_commit) from error

    try:
        # ls-tree учитывает путь текущего каталога от корня репозитория.
        found = git("--literal-pathspecs", "ls-tree", "-z", commit, "--", REVIEWS_NAME)
        if not found:
            return revision, commit, set()
        if found.count(b"\0") != 1:
            raise ReviewError(tr("checker.audit.review_path_ambiguous"))
        mode, kind, oid = found.split(b"\t", 1)[0].split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ReviewError(tr("checker.audit.review_file_expected"))
        data = parse_reviews(git("cat-file", "blob", oid.decode("ascii")))
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReviewError(tr("checker.audit.review_unreadable_at_commit") % commit) from error
    except ReviewError as error:
        raise ReviewError(tr("checker.audit.review_at_commit") % (commit, error)) from error
    return revision, commit, {entry["id"] for entry in data["entries"]}


def _by_reviewer(entries):
    authors = {}
    for entry in entries:
        reviewer, stamp = entry["reviewer"], entry["reviewed_at"]
        row = authors.setdefault(reviewer, {"reviewer": reviewer, "count": 0,
                                            "last_reviewed_at": stamp})
        row["count"] += 1
        row["last_reviewed_at"] = max(row["last_reviewed_at"], stamp)
    return [authors[reviewer] for reviewer in sorted(authors)]


# --- Аудит -------------------------------------------------------------------

def audit(pr, rep, docs, anchor_ids, tags, tag_lines, *, reviews_base=None):
    today = datetime.date.today()
    days = pr.cfg["stale_days"]

    def age(d):
        v = d["header"].get(K_UPDATED, "")
        try:
            return (today - datetime.date.fromisoformat(v)).days
        except ValueError:
            return None

    # @trace docs/ru/codes.md#a1
    for did, d in sorted(docs.items()):
        r, a, st = pr.rel(d["page"].path), age(d), d.get("status")
        if a is not None:
            if d["prefix"] == "pln" and st in ("new", "in progress") and a > days["active"]:
                rep.finding("A1", r, 0, tr("checker.audit.inactive_plan")
                         % (st, a), subject=did)
            if d["prefix"] == "pln" and st == "pending acceptance" and a > days["review"]:
                rep.finding("A1", r, 0, tr("checker.audit.awaiting_acceptance") % a, subject=did)
            if d["prefix"] == "iss" and st in ("open", "in progress") and a > days["issue"]:
                rep.finding("A1", r, 0, tr("checker.audit.open_issue") % a, subject=did)
        # @trace docs/ru/codes.md#a2
        lim = pr.cfg["limits"]["workflow_lines"]
        if lim and d["page"].lines > lim:
            rep.finding("A2", r, 0, tr("checker.audit.oversized_workflow_document")
                     % (d["page"].lines, lim), subject=did)

        # @trace docs/ru/codes.md#a8
        if d["prefix"] in ("pln", "iss") and st in STATUSES[d["prefix"]] \
                and st not in FINAL and K_DUE in d["header"]:
            value = d["header"][K_DUE]
            try:
                if not RE_DATE.fullmatch(value):
                    raise ValueError
                due = datetime.date.fromisoformat(value)
            except ValueError:
                rep.finding("A8", r, d["page"].h1_line,
                            tr("checker.audit.invalid_due_date")
                            % (K_DUE, value), subject=K_DUE)
            else:
                if due < today:
                    rep.finding("A8", r, 0,
                                tr("checker.audit.overdue_work_item")
                                % (value, st), subject=did)

    # @trace docs/ru/codes.md#a7
    open_discussions = {d["page"].path: did for did, d in docs.items()
                        if d["prefix"] == "dsc" and d.get("status") == "open"}
    for did, d in sorted(docs.items()):
        if d["prefix"] != "adr" or d.get("status") != "accepted":
            continue
        seen = set()
        for line, target in d["page"].links:
            path, _ = resolve_target(d["page"], target, pr)
            discussion = open_discussions.get(path)
            if discussion is None or discussion in seen:
                continue
            seen.add(discussion)
            rep.finding("A7", pr.rel(d["page"].path), line,
                        tr("checker.audit.accepted_decision_open_discussion") % discussion.upper(),
                        subject=discussion)

    # A5: статус отстал от коммитов с ID работы. История — репозитория
    # проекта (pr.root), даже если рабочие материалы лежат в другом.
    # @trace docs/ru/codes.md#a5
    def commits_after(since):
        """[(короткий хеш, сообщение)] коммитов после since или None при сбое."""
        if pr.git_root is None:
            return None
        scope = ("--", ".") if pr.root != pr.git_root else ()
        try:
            out = subprocess.run(["git", "-C", str(pr.root), "log",
                                  "--format=%h%x00%s", "--since=%s" % since, *scope],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 check=True).stdout.decode("utf-8", "replace")
        except (OSError, subprocess.CalledProcessError):
            return None
        return [s.split("\x00", 1) for s in out.split("\n") if "\x00" in s]

    closed = {"completed", "canceled", "closed"}
    for did, d in sorted(docs.items()):
        st = d.get("status")
        if st not in ("new", "deferred") and \
                not (d["prefix"] in ("pln", "iss") and st in closed):
            continue
        updated = d["header"].get(K_UPDATED, "")
        if not RE_DATE.match(updated):
            continue
        commits = commits_after("%sT23:59:59" % updated)
        if not commits:
            continue
        matched = []
        for h, msg in commits:
            m = RE_DOC_REF.search(msg)
            if m and "%s-%s" % (m.group(1).lower(), m.group(2)) == did:
                matched.append(h)
        if not matched:
            continue
        n = len(matched)
        word = (tr("checker.audit.commit_singular") if n % 10 == 1 and n % 100 != 11 else
                tr("checker.audit.commit_few") if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
                else tr("checker.audit.commit_many"))
        reason = (tr("checker.audit.unrecorded_work") if st in ("new", "deferred")
                  else tr("checker.audit.work_continued_after_closure"))
        rep.finding("A5", pr.rel(d["page"].path), 0,
                    tr("checker.audit.commits_after_status") % {
                        "id": did.upper(), "count": n, "word": word, "updated": updated,
                        "latest": matched[0], "reason": reason,
                    }, subject=did)

    # @trace docs/ru/codes.md#a3
    if pr.cfg["entry"]:
        entry_res = [re.compile(x) for x in pr.cfg["entry"]]
        code_file = re.compile(r"\.(?:%s)$" % CODE_EXT)
        skip = set(x for x in (pr.docs, pr.wf, pr.decisions) if x is not None)
        for path in pr.walk_files(skip=skip, resolved=True,
                                  path_filter=lambda p: bool(code_file.search(p.name))):
            r = pr.rel(path)
            if is_test_file(r):
                continue
            text = read_text(path)
            if text is None:
                continue
            lines = physical_lines(text)
            for n, s in enumerate(lines):
                if any(x.search(s) for x in entry_res) and \
                        not any(any(trace_matches(y)) for y in lines[max(0, n - 3):n + 1]):
                    rep.finding("A3", r, n + 1, tr("checker.audit.entry_without_trace") % s.strip()[:80])

    # @trace docs/ru/codes.md#a4,docs/ru/review.md#state
    reviews = ReviewContext(pr)
    pr.reviews_present = reviews.registry is not None
    pr.reviewed_pairs = set()
    entries = reviews.registry["entries"] if pr.reviews_present else []
    pr.reviews_since = None
    if reviews_base is not None:
        revision, commit, old_ids = reviews_base
        added = [entry for entry in entries if entry["id"] not in old_ids]
        pr.reviews_since = {"revision": revision, "commit": commit, "count": len(added),
                            "by_reviewer": _by_reviewer(added)}
    obsolete, unchecked = reviews.lifecycle()
    pr.reviewed_obsolete, pr.reviewed_unchecked = len(obsolete), len(unchecked)
    history = GitBlame(pr.root)
    dated_sections = {}
    requests = []
    for pair in reviews.pairs:
        target = pair['target_id']
        if target not in dated_sections:
            dated_sections[target] = history.lines_time(pair['target']['path'], pair['target_numbers'])
        t_doc = dated_sections[target]
        if t_doc:
            requests.append((pair['source']['path'], pair['history_line'], pair['boundaries'], t_doc))
    history.preload_staleness(requests)
    for pair in reviews.pairs:
        i, cfile = pair['target_id'], pair['source']['path']
        t_doc = dated_sections[i]
        if not t_doc:
            continue
        t_code = history.stale_region_time(cfile, pair['history_line'], pair['boundaries'], since=t_doc)
        if t_code and t_code > t_doc:
            if pr.cfg.get('codes', {}).get('A4') != 'off' and reviews.acknowledges(pair):
                pr.reviewed_pairs.add(pair['id'])
                continue
            rep.finding("A4", pair['target']['path'], pair['target_line'],
                        tr("checker.audit.code_newer_than_documentation")
                        % (i, cfile,
                           datetime.datetime.fromtimestamp(t_code, datetime.timezone.utc).isoformat(),
                           datetime.datetime.fromtimestamp(t_doc, datetime.timezone.utc).isoformat()),
                        subject=i)
    pr.reviewed_by = _by_reviewer(entry for entry in entries if entry["id"] in pr.reviewed_pairs)

    # A6: размер базовой линии по кодам — сколько долга зафиксировано и каких.
    # @trace docs/ru/codes.md#a6
    entries = read_baseline(pr.root)
    if entries:
        by_code = {}
        for entry in entries:
            by_code[entry["code"]] = by_code.get(entry["code"], 0) + entry["count"]
        by_code = {code: n for code, n in by_code.items() if n > 0}
        if by_code:
            rep.finding("A6", BASE_NAME, 0, tr("checker.audit.baseline")
                     % ", ".join("%s — %d" % (code, n) for code, n in sorted(by_code.items())))
