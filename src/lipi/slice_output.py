"""Общий отбор содержимого среза и его текстовое представление."""
import copy
import re
from collections import Counter
from itertools import islice

from .checker.model import mask_code
from .i18n import plural_form, quoted, tr
from .repo_index import qualify
from .slice_diff_budget import section_line_count, trim_sections


BLOCK_KINDS = ("signals", "obey", "excerpt", "concepts", "entry", "code", "tests", "targets", "context")


def _short_excerpt(lines, limit):
    """Первый абзац/пункт, заголовки и ссылки в исходном порядке строк."""
    if len(lines) <= limit:
        return lines
    masked = mask_code("\n".join(lines)).split("\n")
    bullet = re.compile(r"^(\s*)(?:[-+*]|\d+[.)])\s+")
    keep = set()
    paragraph = False
    list_indent = None
    first = next((n for n, line in enumerate(lines) if line.strip()), None)
    for n, (line, structure) in enumerate(zip(lines, masked)):
        if re.match(r"^\s*#{1,6}\s", structure) or not line.strip() or not structure:
            if paragraph:
                break
            continue
        item = bullet.match(line)
        indent = len(item[1].expandtabs(4)) if item else None
        if paragraph and item and (list_indent is None or indent <= list_indent):
            break
        if not paragraph:
            list_indent = indent
        paragraph = True
        keep.add(n)
    for n, line in enumerate(masked):
        if (n != first and re.match(r"^\s*#{1,6}\s", line)) or re.search(
                r"\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])|^\s*\[[^\]]+\]:|https?://", line):
            keep.add(n)
    selected = [line for n, line in enumerate(lines) if n in keep]
    return (selected or lines)[:limit]


def _block_rows(block):
    """Объявление под понятием занимает свою строку после строки понятия."""
    if block["kind"] != "concepts":
        yield from range(len(block["items"]))
        return
    for number, item in enumerate(block["items"]):
        yield number
        for location_number in range(len(item.get("locations", ()))):
            yield number, location_number


# @trace docs/ru/slice.md#budget
def select_response(response, budget=60, full=False, only=None):
    """Один отбор для text и JSON; полный исходный ответ не меняется."""
    result = copy.deepcopy(response)
    if "error" in result:
        return result
    wanted = set(only.split(",") if isinstance(only, str) else only or ())
    blocks = [block for block in result["blocks"]
              if not wanted or block["kind"] == "signals" or block["kind"] in wanted]
    result["blocks"] = blocks
    cap = max(1, budget // 3)
    diff = result.get("checks", {}).get("diff", {})
    diff_index = None
    if wanted and "excerpt" not in wanted:
        diff.pop("sections", None)
        diff.pop("sections_omitted", None)
    elif not full and diff.get("sections"):
        diff_lines = section_line_count(diff["sections"])
        diff_index = next((index for index, block in enumerate(blocks)
                           if block["kind"] not in ("signals", "obey")), len(blocks))
        # Все разделы вместе получают долю одной выдержки.
        excerpt = {"kind": "excerpt", "items": []}
        blocks = blocks[:diff_index] + [excerpt] + blocks[diff_index:]

    remaining = budget
    selected = [set() for _ in blocks]
    excerpts = {}
    for index, block in enumerate(blocks):
        if block["kind"] == "excerpt" and block["items"]:
            original = block["items"][0]["text"].splitlines()
            excerpts[index] = (original, original if full else _short_excerpt(original, cap))

    def take(index, candidates, limit):
        nonlocal remaining
        count = min(limit, remaining)
        if count <= 0:
            return
        choices = (n for n in candidates if n not in selected[index])
        chosen = list(islice(choices, count))
        selected[index].update(chosen)
        remaining -= len(chosen)

    # Серьёзные сигналы получают первую половину; порядок уже задан сборщиком.
    reserve = max(1, budget // 2)
    for index, block in enumerate(blocks):
        if block["kind"] == "signals":
            take(index, [n for n, item in enumerate(block["items"])
                         if item["level"] in ("error", "warning")], reserve)

    # Затем доля каждого блока, включая info, но не полную выдержку.
    for index, block in enumerate(blocks):
        if index == diff_index:
            take(index, range(min(cap, diff_lines)), 3)
        elif block["kind"] == "excerpt":
            if index in excerpts:
                lines = excerpts[index][1]
                if full:
                    selected[index].update(range(len(lines)))
                else:
                    take(index, range(len(lines)), 3)
        elif block["kind"] == "signals":
            take(index, [n for n, item in enumerate(block["items"])
                         if item["level"] == "info"], 3)
        else:
            take(index, _block_rows(block), 3)

    # Остаток — сначала серьёзным сигналам, потом по порядку ответа.
    for index, block in enumerate(blocks):
        if block["kind"] == "signals":
            take(index, [n for n, item in enumerate(block["items"])
                         if item["level"] in ("error", "warning")], remaining)
    for index, block in enumerate(blocks):
        if index == diff_index:
            take(index, range(min(cap, diff_lines)), remaining)
        elif block["kind"] == "excerpt":
            if index in excerpts and not full:
                take(index, range(len(excerpts[index][1])), remaining)
        else:
            take(index, _block_rows(block), remaining)

    incomplete = result['incomplete']
    if diff_index is not None:
        shown = len(selected[diff_index])
        if shown < diff_lines:
            trim_sections(diff, shown)
            incomplete = True
    for index, block in enumerate(blocks):
        if index == diff_index:
            continue
        kind, items = block["kind"], block["items"]
        if index in excerpts:
            original, shortened = excerpts[index]
            lines = [line for n, line in enumerate(shortened) if n in selected[index]]
            omitted = len(original) - len(lines)
            block["items"] = [{**items[0], "text": "\n".join(lines),
                               "lines": len(lines), "cut": bool(omitted)}] if lines else []
        else:
            block["items"] = [item for n, item in enumerate(items) if n in selected[index]]
            omitted = len(items) - len(block["items"])
            if kind == "concepts":
                for number, item in enumerate(items):
                    locations = item.get("locations", ())
                    if number not in selected[index] or not locations:
                        continue
                    visible = [location for location_number, location in enumerate(locations)
                               if (number, location_number) in selected[index]]
                    hidden = len(locations) - len(visible)
                    if hidden:
                        item.update(locations=visible, locations_omitted=hidden)
                        incomplete = True
        block["omitted"] = omitted
        block["hint"] = (["--full"] if kind == "excerpt" else ["--only " + kind]) if omitted else []
        if omitted and kind in ("entry", "code", "tests"):
            block["hint"].append("--layer")
        incomplete = incomplete or bool(omitted)
    result["incomplete"] = incomplete
    return result


def count_text(number, kind):
    return tr("slice.count." + kind + "." + plural_form(number)) % number


def _summary(summary):
    parts = []
    for key in ("errors", "warnings", "decisions", "rules", "concepts", "entry",
                "code", "tests", "open_work", "targets"):
        number = summary.get(key, 0)
        if not number:
            continue
        part = count_text(number, key)
        if key == "code" and summary.get("layers"):
            detail = count_text(summary["layers"], "layers")
            if "repos" in summary:
                detail += ", " + count_text(summary["repos"], "repos")
            part += " (%s)" % detail
        parts.append(part)
    roles = summary.get("roles", {})
    if "role" in roles:
        parts.append(count_text(roles["matched"], roles["role"]))
        unassigned = roles["unassigned"]
        if unassigned:
            parts.append(tr("slice.role.additional." + plural_form(unassigned)) % unassigned)
    elif roles.get("unassigned"):
        parts.append(tr("slice.role.unassigned_locations") % roles["unassigned"])
    if roles.get("unrecognized"):
        parts.append(count_text(roles["unrecognized"], "unrecognized"))
    return " · ".join(parts)


# @trace docs/ru/slice-diff.md#response
def _diff_target_labels(blocks):
    targets = {qualify(item.get("repo"), item["target"])
               for block in blocks if block["kind"] == "concepts" for item in block["items"]}
    if len(targets) < 2:
        return {}
    anchors = Counter(target.partition("#")[2] for target in targets)
    labels = {}
    for target in targets:
        anchor = target.partition("#")[2]
        labels[target] = "#" + anchor if anchor and anchors[anchor] == 1 else target
    return labels


def _diff_reason_text(reasons, labels, roles):
    by_target = {}
    for reason in reasons:
        target = reason["target"]
        details = by_target.setdefault(target, [])
        kind, link = reason["reason"], reason.get("link")
        if kind in ("code-change", "decision-number"):
            details.append(kind)
        if link == "removed":
            details.append("link-removed")
        elif kind == "target-removed":
            details.append("new-link-to-deleted" if link == "added" else "link-to-deleted")
        elif link == "added":
            details.append("link-added")
        elif kind == "contract-change":
            details.append(kind)

    def detail(key):
        return tr("slice.diff.reason." + key)

    common_change = len(by_target) > 1 and all("code-change" in keys for keys in by_target.values())
    parts = [detail("code-change")] if common_change else []
    for target, keys in by_target.items():
        keys = dict.fromkeys(keys)
        if common_change:
            del keys["code-change"]
        label = labels.get(target, target)
        details = [detail(key) for key in keys]
        if target in roles:
            details.append(roles[target])
        if details:
            label += " (%s)" % ", ".join(details)
        parts.append(label)
    return " — " + ", ".join(parts)


def _diff_sections_text(diff):
    sections = diff.get("sections", ())
    omitted = diff.get("sections_omitted", 0)
    if not sections and not omitted:
        return []
    lines = [tr("slice.diff.sections")]
    for section in sections:
        lines.append("  " + section["target"])
        for side in ("before", "after"):
            text = section[side]
            key = "slice.diff.section." + side
            lines.append("    " + tr(key + ".absent" if text is None else key))
            if text:
                lines.extend("      " + row for row in text.split("\n"))
        if section.get("omitted"):
            hidden = section["omitted"]
            note = tr("slice.diff.section.lines-omitted") % (hidden["before"], hidden["after"])
            lines.append("  " + tr("slice.render.show_more") % (note, "--full"))
        if section.get("linked") is False:
            lines.append("    " + tr("slice.diff.section.no-links"))
    if omitted:
        note = tr("slice.diff.sections_omitted") % omitted
        lines.append(tr("slice.render.show_more") % (note, "--full"))
    return lines


def _place_address(item):
    return "%s:%s  %s" % (qualify(item.get("repo"), item["path"]), item["line"], item["symbol"])


def _role_text(entry):
    roles = [tr("slice.role." + role) for role in entry["roles"]]
    roles.extend(tr("slice.role.unrecognized") % quoted(value)
                 for value in entry.get("invalid_roles", ()))
    return ", ".join(roles) or tr("slice.role.unassigned")


def _via_text(targets, labels, roles):
    descriptions = []
    for target in targets:
        label = labels.get(target, target)
        if target in roles:
            label += " (%s)" % roles[target]
        descriptions.append(label)
    return tr("slice.render.via") % ", ".join(descriptions) if descriptions else ""


def _item_text(kind, item, labels):
    if kind in ("entry", "code", "tests"):
        text = _place_address(item)
        if kind != "tests":
            text += "  [%s]" % qualify(item.get("repo"), item["layer"])
        if item.get("side") == "before":
            text += " [%s]" % tr("slice.diff.place.before")
        roles = {entry["target"]: _role_text(entry) for entry in item.get("target_roles", ())}
        if item.get("reasons"):
            return text + _diff_reason_text(item["reasons"], labels, roles)
        targets = item["matched_targets"] if labels else roles
        return text + _via_text(targets, labels, roles)
    if item.get("repo"):
        item = dict(item)
        if "path" in item:
            item["path"] = qualify(item["repo"], item["path"])
        if "target" in item and kind != "signals":
            item["target"] = qualify(item["repo"], item["target"])
    if kind == "signals":
        if item.get("code"):
            prefix = "! %s  " % item["code"]
            if item.get("path"):
                prefix += item["path"]
                if item.get("line"):
                    prefix += ":%s" % item["line"]
                prefix += " — "
            return prefix + item["message"]
        return "· " + item["message"]
    text = item["target"]
    if kind == "obey" and item.get("status"):
        text += " " + item["status"]
    text += " — " + item["title"]
    if kind == "obey":
        text += " (%s)" % item["relation"]
        if item.get("via"):
            text += tr("slice.render.via") % ", ".join(item["via"])
    if kind in ("concepts", "targets"):
        text += " (%s)" % count_text(item["code_count"], "code")
    return text


def _concept_locations(item):
    locations = item.get("locations", ())
    for location in locations:
        roles = {entry["target"]: _role_text(entry) for entry in location["target_roles"]}
        yield "    " + _place_address(location) + _via_text(roles, {}, roles)
    omitted = item.get("locations_omitted", 0)
    if omitted:
        yield "    " + tr("slice.render.locations_omitted") % (len(locations), len(locations) + omitted)


# @trace docs/ru/slice-search.md#output
def render_search_text(response):
    candidates = response["candidates"]
    lines = []
    if not response.get("incomplete"):
        lines.append(tr("slice.search.results") % (response["total"], len(candidates)))
    if response.get("message"):
        lines.append(response["message"])
    for item in candidates:
        lines.append("  %s — %s" % (qualify(item["repo"], item["target"]), item["title"]))
        lines.append("    %s:%d" % (item["file"], item["line"]))
        lines.append("    " + item["excerpt"])
    if response.get("suggestions"):
        lines.append(tr("slice.search.suggestions"))
        lines.extend("  " + item["command"] for item in response["suggestions"])
    return "\n".join(lines)


# @trace docs/ru/slice.md#json
def render_text(response, *, target_path=None, selected_blocks=None, selected_response=None):
    """Render selected items and sections using all concepts to disambiguate target labels."""
    if "error" in response:
        key = "slice.render.ambiguous" if response["error"] == "ambiguous" else "slice.render.not_found"
        candidates = tr("slice.render.candidates") if response.get("candidates") else ""
        lines = [tr(key) % (response["query"], candidates)]
        if response.get("message"):
            lines.append(response["message"])
        lines += ["  %s — %s" % ((item["repo"] + "::" if item.get("repo") else "") + item["target"], item["title"])
                  for item in response.get("candidates", [])]
        if response.get("search_command"):
            lines.extend([tr("slice.render.search"), "  " + response["search_command"]])
        if response.get("suggestions"):
            lines.append(tr("slice.render.suggestions"))
            lines.extend("  " + item["command"] for item in response["suggestions"])
        from .repo_output import render_repository_status
        lines.extend(render_repository_status(response))
        lines.extend(note["text"] for note in response.get("notes", []))
        return "\n".join(lines)
    target = response["target"]
    title = target.get("title", "")
    if target["kind"] == "code":
        title = tr("slice.code.title") + (" [%s]" % target["layer"] if target.get("layer") else "")
    line = ((target["repo"] + "::" if target.get("repo") else "") + target["target"]
            + (" — " + title if title else ""))
    if target.get("status"):
        line += " (%s)" % target["status"]
    if target.get("found") not in (None, "exact"):
        line += tr("slice.render.found") % target["found"]
    lines = [line]
    if target_path:
        lines.append(tr("slice.render.open_path") % target_path)
    summary = _summary(response["summary"])
    if summary:
        lines.append(summary)
    if "reviewed_pairs" in response["summary"]:
        lines.append(tr("slice.render.reviewed") % response["summary"]["reviewed_pairs"])
    from .repo_output import render_repository_status
    lines.extend(render_repository_status(response))
    lines.extend(note["text"] for note in response.get("notes", []))
    labels = _diff_target_labels(response["blocks"]) if target["kind"] == "diff" else {}
    display = response if selected_response is None else selected_response
    blocks = display["blocks"] if selected_blocks is None else selected_blocks
    body = []
    section_offset = 0
    for block in blocks:
        if not block["items"] and not block["omitted"]:
            continue
        kind = block["kind"]
        body.append(tr("slice.block." + kind))
        for item in block["items"]:
            content = item["text"].splitlines() if kind == "excerpt" else [_item_text(kind, item, labels)]
            body.extend("  " + line for line in content)
            if kind == "concepts":
                body.extend(_concept_locations(item))
        if block["omitted"]:
            hints = ", ".join(block["hint"])
            shown = sum(item["lines"] for item in block["items"]) if kind == "excerpt" else len(block["items"])
            total = shown + block["omitted"]
            if kind == "excerpt":
                hidden = tr("slice.render.excerpt_omitted") % (shown, total)
            elif kind == "concepts" and target["kind"] == "code":
                count = block["omitted"]
                hidden = tr("slice.render.concepts_omitted." + plural_form(count)) % count
            elif kind == "signals":
                hidden = tr("slice.render.signals_omitted") % (shown, total)
            else:
                hidden = tr("slice.render.omitted") % (shown, total)
            body.append(tr("slice.render.show_more") % (hidden, hints))
        if kind in ("signals", "obey"):
            section_offset = len(body)
    body[section_offset:section_offset] = _diff_sections_text(display.get("checks", {}).get("diff", {}))
    if body:
        lines.extend(["", *body])
    return "\n".join(lines)
