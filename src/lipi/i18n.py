"""Personal interface language and packaged translation resources."""
import argparse
import contextvars
import functools
import gettext
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from contextlib import contextmanager


LOCALE = Path(__file__).resolve().parent / "locale"
_language = contextvars.ContextVar("lipi_output_language", default=None)
_parser_lock = threading.RLock()
_personal = contextvars.ContextVar("lipi_personal_language", default=None)


def available_languages():
    return sorted(p.name for p in LOCALE.iterdir()
                  if p.is_dir() and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", p.name))


def _config_path():
    return Path.home() / ".config" / "lipi" / "config.json"


def _settings():
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")
    return data


def current_language():
    if _personal.get() is not None:
        return _personal.get()
    try:
        value = _settings().get("language", "en")
    except (OSError, ValueError):
        return "en"
    return value if value in available_languages() else "en"


def set_language(language):
    if language not in available_languages():
        raise ValueError(language)
    path = _config_path()
    settings = _settings()
    settings["language"] = language
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temp = Path(stream.name)
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def output_language():
    return _language.get() or current_language()


@contextmanager
def use_language(language):
    token = _language.set(language)
    try:
        yield
    finally:
        _language.reset(token)


def output_format(argv):
    fmt = "text"
    for i, arg in enumerate(argv):
        if arg == "--":
            break
        option, equals, value = arg.partition("=")
        if option.startswith("--f") and "--format".startswith(option):
            if equals:
                fmt = value
            elif i + 1 < len(argv):
                fmt = argv[i + 1]
    return fmt


def cli_output(main):
    """Keep human-readable fields of a machine response in canonical English."""
    @functools.wraps(main)
    def wrapper(*args, **kwargs):
        argv = args[0] if args else kwargs.get("argv")
        argv = sys.argv[1:] if argv is None else argv
        fmt = output_format(argv)
        personal = current_language()
        token = _personal.set(personal)
        try:
            with use_language("en" if fmt == "json" else personal):
                return main(*args, **kwargs)
        finally:
            _personal.reset(token)
    return wrapper


def _object(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _catalog(root, language, part):
    return _object(root / language / (part + ".json"))


def _translation(part, entry):
    value = entry.get("text") if isinstance(entry, dict) else None
    if part == "terms":
        if isinstance(value, dict) and all(isinstance(value.get(field), str)
                                           for field in ("term", "definition")):
            return value
    elif isinstance(value, str):
        return value
    return None


def _entry(part, key, language):
    english = _catalog(LOCALE, "en", part)[key]
    if language != "en":
        translated = _translation(part, _catalog(LOCALE, language, part).get(key))
        if translated is not None:
            return translated
    return english


def tr(key, language=None):
    return _entry("messages", key, language or output_language())


def quoted(text):
    return tr("common.quote") % text


def term(key, language=None):
    """Return a preferred term and its short definition."""
    return _entry("terms", key, language or output_language())


def template_path(relative, language=None):
    """Resolve a localized seed or an English managed template."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(relative)
    if relative.parts[:1] == ("seed",):
        language = language or current_language()
        candidate = LOCALE / language / "templates" / relative
        if language != "en" and candidate.exists():
            return candidate
    return LOCALE / "en" / "templates" / relative


def fingerprint(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def translation_report(language):
    """Inventory missing and stale message, term, and seed template translations."""
    report = {"missing": [], "stale": []}
    if language == "en":
        return report
    for part in ("messages", "terms"):
        base = _object(LOCALE / "en" / (part + ".json"))
        translated = _object(LOCALE / language / (part + ".json"))
        for key, value in sorted(base.items()):
            item = translated.get(key)
            label = part + "/" + key
            if _translation(part, item) is None:
                report["missing"].append(label)
            elif item.get("source_sha256") != fingerprint(value):
                report["stale"].append(label)
    templates = LOCALE / "en" / "templates"
    hashes = _object(LOCALE / language / "template-hashes.json")
    for source in sorted(p for p in (templates / "seed").rglob("*") if p.is_file()):
        path = source.relative_to(templates).as_posix()
        label = "templates/" + path
        if not (LOCALE / language / label).is_file():
            report["missing"].append(label)
        elif hashes.get(path) != fingerprint(source.read_text(encoding="utf-8")):
            report["stale"].append(label)
    return report


class ArgumentParser(argparse.ArgumentParser):
    """Use the personal interface language for standard parser messages as well."""
    @contextmanager
    def _translations(self):
        def translate(text):
            key = "argparse." + text
            if key in _catalog(LOCALE, "en", "messages"):
                return tr(key)
            return text

        # argparse resolves gettext at module scope during construction and rendering.
        with _parser_lock:
            original = argparse._
            argparse._ = translate
            try:
                yield
            finally:
                argparse._ = original

    def __init__(self, *args, **kwargs):
        with self._translations():
            super().__init__(*args, **kwargs)

    def format_help(self):
        with self._translations():
            return super().format_help()

    def format_usage(self):
        with self._translations():
            return super().format_usage()

    def parse_args(self, *args, **kwargs):
        with self._translations():
            return super().parse_args(*args, **kwargs)

    def parse_known_args(self, *args, **kwargs):
        with self._translations():
            return super().parse_known_args(*args, **kwargs)


def plural_form(number, language=None):
    rule = tr("grammar.plural", language)
    return ("one", "few", "ending_one", "other")[_plural_selector(rule)(number)]


_plural_selector = functools.lru_cache(maxsize=None)(gettext.c2py)
