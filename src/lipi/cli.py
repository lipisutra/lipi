#!/usr/bin/env python3
"""Command dispatcher for lipi."""
import subprocess
import sys
import sysconfig
from pathlib import Path

# На Windows stdout по умолчанию в кодировке консоли (cp1252), и русские
# сообщения роняли бы печать. Команда lipi всегда печатает в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
REPO = SRC.parent
PACKAGE = HERE
PACKAGE_CHECK = HERE / "check.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SRC))
from lipi import __version__ as VERSION  # noqa: E402

from lipi.i18n import available_languages, current_language, set_language, tr

SETUP_URL = "https://github.com/lipisutra/lipi/blob/v%s/SETUP.md" % VERSION


def run(script, args):
    return subprocess.call([sys.executable, "-B", str(script)] + list(args))


def packaged_doc(name):
    """Страница по пути от корня описания: репозитория или share/lipi.

    В обоих местах путь одинаков: например, SETUP.md или docs/en/commands.md.
    """
    repo = REPO / name
    if repo.is_file():
        return repo
    try:
        shared = Path(sysconfig.get_path("data")) / "share" / "lipi" / name
    except (KeyError, TypeError):
        return None
    return shared if shared.is_file() else None


def setup_text():
    """Текст SETUP.md; у установленного пакета он лежит в share/lipi."""
    path = packaged_doc("SETUP.md")
    return path.read_text(encoding="utf-8") if path is not None else None


def main():
    argv = sys.argv[1:]
    cmd, rest = (argv[0], argv[1:]) if argv else ("help", [])
    # @trace docs/ru/commands.md#help
    if cmd in ("help", "-h", "--help", "?", "/?"):
        if rest in (["slice"], ["map"], ["mv"], ["review"]):
            module = "move" if rest == ["mv"] else rest[0]
            return run(PACKAGE / (module + ".py"), ["--help"])
        print(tr("cli.help"))
        return 0
    # @trace docs/ru/commands.md#lang
    if cmd == "lang":
        if not rest:
            print(current_language())
            return 0
        if rest == ["--help"] or rest == ["-h"]:
            print(tr("lang.usage"))
            return 0
        if len(rest) != 1:
            print(tr("lang.usage"), file=sys.stderr)
            return 2
        language = rest[0]
        if language not in available_languages():
            print(tr("lang.unknown") % (language, ", ".join(available_languages())), file=sys.stderr)
            return 2
        try:
            set_language(language)
        except (OSError, ValueError) as exc:
            print(tr("lang.settings") % exc, file=sys.stderr)
            return 2
        print(language)
        return 0
    # @trace docs/ru/commands.md#guide
    if cmd == "guide":
        text = setup_text()
        if text is None:
            print(tr("cli.setup_url")
                  % SETUP_URL)
            return 1
        print(text.rstrip())
        return 0
    # @trace docs/ru/commands.md#update
    if cmd == "init":
        has_dir = bool(rest) and not rest[0].startswith("-")
        return run(PACKAGE / "init.py", rest if has_dir else ["."] + rest)
    # @trace docs/ru/commands.md#ci
    if cmd == "ci":
        if not rest or rest[0] != "github":
            print(tr("cli.ci_provider"), file=sys.stderr)
            return 2
        args = rest[1:]
        has_dir = bool(args) and not args[0].startswith("-")
        return run(PACKAGE / "init.py",
                   (args if has_dir else ["."] + args)
                   + ["--ci", "github", "--ci-only"])
    # @trace docs/ru/commands.md#migrate
    if cmd == "migrate":
        return run(PACKAGE / "migrate.py", rest)
    # @trace docs/ru/commands.md#mv
    if cmd == "mv":
        return run(PACKAGE / "move.py", rest)
    # @trace docs/ru/commands.md#check
    if cmd == "check":
        return run(PACKAGE_CHECK, rest)
    # @trace docs/ru/commands.md#audit
    if cmd == "audit":
        return run(PACKAGE_CHECK, ["--audit"] + rest)
    # @trace docs/ru/commands.md#slice
    if cmd == "slice":
        return run(PACKAGE / "slice.py", rest)
    # @trace docs/ru/commands.md#review
    if cmd == "review":
        return run(PACKAGE / "review.py", rest)
    # @trace docs/ru/commands.md#map
    if cmd == "map":
        return run(PACKAGE / "map.py", rest)
    # @trace docs/ru/commands.md#doctor
    if cmd == "doctor":
        return run(PACKAGE / "doctor.py", rest)
    # @trace docs/ru/commands.md#index
    if cmd == "index":
        return run(PACKAGE_CHECK, ["--write-index"] + rest)
    # @trace docs/ru/commands.md#baseline
    if cmd == "baseline":
        return run(PACKAGE_CHECK, ["baseline"] + rest)
    # @trace docs/ru/commands.md#new
    if cmd == "new":
        return run(PACKAGE_CHECK, ["new"] + rest)
    # @trace docs/ru/commands.md#friction
    if cmd == "collect":
        return run(PACKAGE / "collect.py", rest)
    # @trace docs/ru/commands.md#selftest
    if cmd == "selftest":
        tests = REPO / "tests"
        if not tests.is_dir():
            print(tr("cli.no_tests") % tests.parent,
                  file=sys.stderr)
            return 2
        return subprocess.call(
            [sys.executable, "-m", "unittest", "discover", "-s", str(tests)]
            + list(rest), cwd=str(REPO))
    # @trace docs/ru/commands.md#version
    if cmd in ("version", "--version"):
        print("lipi %s" % VERSION)
        if "--path" in rest:
            print(PACKAGE_CHECK)
        return 0
    print(tr("cli.unknown") % cmd + "\n\n" + tr("cli.help"), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
