#!/usr/bin/env python3
"""collect.py — забирает из проекта замечания, адресованные lipi.

    python3 src/lipi/collect.py /путь/к/проекту [/путь/к/другому ...]

Из установленного пакета — команда lipi collect.

В проекте такое замечание создаётся командой
    lipi new iss "Что мешает" friction lipi
и несёт в шапке строку «- Recipient: lipi». Лежит оно в workflow/issue/
проекта, а если рабочие материалы не подключены — в .agents/lipi-feedback/
(там его тоже видит чекер). Скрипт копирует его в
workflow/issue/ГГГГ/ самого lipi с очередным номером и строкой
«- Source: external <6 знаков хеша> ISS-NNN»: первые шесть знаков SHA-256
от имени каталога проекта в UTF-8. Повторный запуск уже забранное не дублирует.
Перед сбором обезличьте заголовок и текст замечания.
Замечание в проекте остаётся как есть.
"""
import datetime
import hashlib
import sys
from pathlib import Path

# На Windows stdout по умолчанию в кодировке консоли (cp1252), и русские
# сообщения роняли бы печать. Скрипты lipi всегда печатают в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

HERE = Path(__file__).resolve().parent
LIPI = HERE.parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
from lipi.checker.config import load_config  # noqa: E402
from lipi.checker.conventions import (  # noqa: E402
    ISSUE_KINDS, K_ADDRESSEE, K_CREATED, K_KIND, K_SOURCE, K_STATUS,
    K_UPDATED, RE_HEADER, SOURCE_EXTERNAL,
)
from lipi.checker.model import Project  # noqa: E402
from lipi.checker.report import Report  # noqa: E402
from lipi.checker.workflow import scan_workflow, slugify  # noqa: E402
from lipi.checker.workflow_index import refresh_index  # noqa: E402
from lipi.checker.workflow_layout import document_directory, reserved_numbers  # noqa: E402
from lipi.i18n import tr  # noqa: E402


def load(root):
    pr = Project(root, load_config(root, None))
    docs, _ = scan_workflow(pr, Report())
    return pr, docs


def main():
    if len(sys.argv) < 2:
        print(tr('collect.usage'), file=sys.stderr)
        return 2
    if sys.argv[1] in ("-h", "--help"):
        print(tr('collect.usage'))
        return 0
    lipi, lipi_docs = load(LIPI)
    if lipi.wf is None:
        print(tr('collect.workflow_missing'), file=sys.stderr)
        return 2
    have = set(d["header"].get(K_SOURCE, "") for d in lipi_docs.values())
    nums = set(reserved_numbers(lipi, "iss")) | {0}
    today = datetime.date.today().isoformat()
    taken = 0
    for arg in sys.argv[1:]:
        root = Path(arg).resolve()
        try:
            pr, docs = load(root)
        except (ValueError, OSError) as e:
            print(tr('collect.config_unreadable') % (root, e), file=sys.stderr)
            continue
        source_hash = hashlib.sha256(root.name.encode("utf-8")).hexdigest()[:6]
        for did, d in sorted(docs.items()):
            h = d["header"]
            if d["prefix"] != "iss" or h.get(K_ADDRESSEE, "").strip().lower() != "lipi":
                continue
            source = "%s %s %s" % (SOURCE_EXTERNAL, source_hash, did.upper())
            if source in have:
                continue
            rest = d["page"].text.split("\n")[d["page"].h1_line:]
            k = 0
            while k < len(rest) and not rest[k].strip():
                k += 1
            while k < len(rest) and (RE_HEADER.match(rest[k])
                                     or (rest[k].startswith("  ") and rest[k].strip())):
                k += 1
            body = rest[k:]
            num = max(nums) + 1
            nums.add(num)
            name = "iss-%03d-%s.md" % (num, slugify(d["title"]))
            kind = h.get(K_KIND, ISSUE_KINDS[1]).lower()
            head = ["# %s" % d["title"], "",
                    "- %s: %s" % (K_CREATED, today),
                    "- %s: %s" % (K_UPDATED, today),
                    "- %s: open" % K_STATUS,
                    "- %s: %s" % (K_KIND, kind if kind in ISSUE_KINDS else "friction"),
                    "- %s: %s" % (K_SOURCE, source)]
            dst = document_directory(lipi, "iss", today) / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("\n".join(head) + "\n\n" + "\n".join(body).strip("\n") + "\n",
                           encoding="utf-8")
            have.add(source)
            taken += 1
            print(tr('collect.collected') % (source, lipi.rel(dst)))
    if taken:
        lipi, lipi_docs = load(LIPI)
        for d in lipi_docs.values():
            d["status"] = d["header"].get(K_STATUS, "").strip("* .").lower()
        try:
            refresh_index(lipi, lipi_docs)
        except (ValueError, OSError) as error:
            print(tr('collect.index_failed') % error, file=sys.stderr)
            return 2
    print(tr('collect.summary') % taken)
    return 0


if __name__ == "__main__":
    sys.exit(main())
