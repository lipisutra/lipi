"""Общий отбор содержимого среза и его текстовое представление."""
import copy
import re
from collections import Counter

from .checker.model import mask_code
from .i18n import plural_form, tr


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
    remaining = budget
    selected = [set() for _ in blocks]
    excerpts = {}
    cap = max(1, budget // 3)
    for index, block in enumerate(blocks):
        if block["kind"] == "excerpt" and block["items"]:
            original = block["items"][0]["text"].splitlines()
            excerpts[index] = (original, original if full else _short_excerpt(original, cap))

    def take(index, candidates, limit):
        nonlocal remaining
        choices = [n for n in candidates if n not in selected[index]]
        chosen = choices[:min(limit, remaining)]
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
        if block["kind"] == "excerpt":
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
            take(index, range(len(block["items"])), 3)

    # Остаток — сначала серьёзным сигналам, потом по порядку ответа.
    for index, block in enumerate(blocks):
        if block["kind"] == "signals":
            take(index, [n for n, item in enumerate(block["items"])
                         if item["level"] in ("error", "warning")], remaining)
    for index, block in enumerate(blocks):
        if block["kind"] == "excerpt":
            if index in excerpts and not full:
                take(index, range(len(excerpts[index][1])), remaining)
        else:
            take(index, range(len(block["items"])), remaining)

    incomplete = result['incomplete']
    for index, block in enumerate(blocks):
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
    return " · ".join(parts)


# @trace docs/ru/slice-diff.md#response
def _diff_target_labels(blocks):
    from .repo_index import qualify
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


def _item_text(kind, item, labels):
    if item.get("repo"):
        item = dict(item)
        for key in ("path", "layer"):
            if key in item:
                item[key] = item["repo"] + "::" + item[key]
        if "target" in item and kind != "signals":
            item["target"] = item["repo"] + "::" + item["target"]
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
    if kind in ("entry", "code", "tests"):
        text = "%s:%s  %s" % (item["path"], item["line"], item["symbol"])
        if kind != "tests":
            text += "  [%s]" % item["layer"]
        if labels:
            text += tr("slice.render.via") % ", ".join(labels[target] for target in item["matched_targets"])
        return text
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


# @trace docs/ru/slice.md#json
def render_text(response, *, target_path=None, selected_blocks=None):
    """Renders selected blocks using the full diff to disambiguate target labels."""
    if "error" in response:
        key = "slice.render.ambiguous" if response["error"] == "ambiguous" else "slice.render.not_found"
        candidates = tr("slice.render.candidates") if response.get("candidates") else ""
        lines = [tr(key) % (response["query"], candidates)]
        if response.get("message"):
            lines.append(response["message"])
        lines += ["  %s — %s" % ((item["repo"] + "::" if item.get("repo") else "") + item["target"], item["title"])
                  for item in response.get("candidates", [])]
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
    first_block = True
    blocks = response["blocks"] if selected_blocks is None else selected_blocks
    for block in blocks:
        if not block["items"] and not block["omitted"]:
            continue
        kind = block["kind"]
        if first_block:
            lines.append("")
            first_block = False
        lines.append(tr("slice.block." + kind))
        for item in block["items"]:
            content = item["text"].splitlines() if kind == "excerpt" else [_item_text(kind, item, labels)]
            lines.extend("  " + line for line in content)
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
            lines.append(tr("slice.render.show_more") % (hidden, hints))
    return "\n".join(lines)
