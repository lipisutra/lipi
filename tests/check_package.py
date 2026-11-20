#!/usr/bin/env python3
"""Проверка описания после чистой, не editable установки lipi.

Из папки вне репозитория, без PYTHONPATH:
    <installed python> /repo/tests/check_package.py --source /snapshot

Снимок той же ревизии задаёт ожидаемые страницы, ресурсы и байты, не путь импорта.
Скрипт ничего не устанавливает; обычный unittest discover его не запускает.
Проверяются состав и явные якоря обеих редакций, inline-ссылки между
страницами и локальные изображения в Markdown и HTML. Внешние URI и ссылки
на исходники, шаблоны и рабочие материалы считаются отдельно. Reference
definitions требуют расширения этого теста.
"""
import argparse
import ast
from html.parser import HTMLParser
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


SOURCE = None
EDITIONS = (Path("docs/en"), Path("docs/ru"))
CONTRIBUTOR_GUIDES = (Path(".agents/README.md"), Path(".agents/ru/README.md"))
ASSETS = Path("docs/assets")
LOGO = ASSETS / "logo.png"


class HtmlTargets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag in ("img", "a"):
            for name, value in attrs:
                if (tag, name) in (("img", "src"), ("a", "href")):
                    self.sources.append((self.getpos()[0], value or "", tag == "img"))


def document_links(page, model):
    from lipi.checker.conventions import RE_LINK
    for match in RE_LINK.finditer(page.masked):
        start = match.start()
        is_image = start > 0 and page.masked[start - 1] == "!"
        yield model.line_of(page.masked, start), match[1], is_image
    images = HtmlTargets()
    images.feed(page.masked)
    images.close()
    yield from images.sources


class InstalledPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SOURCE is None:
            raise AssertionError("Запустите check_package.py с --source /snapshot")
        cls.source = SOURCE
        checkout = Path(__file__).resolve().parents[1]
        for root in (cls.source, checkout):
            if Path.cwd().resolve().is_relative_to(root):
                raise AssertionError("Запустите проверку из папки вне source и репозитория")
        if os.environ.get("PYTHONPATH"):
            raise AssertionError("Уберите PYTHONPATH для проверки установленного пакета")

        cls.dist = importlib.metadata.distribution("lipi")
        direct_url = json.loads(cls.dist.read_text("direct_url.json") or "{}")
        if direct_url.get("dir_info", {}).get("editable"):
            raise AssertionError("Нужна обычная установка, не editable")
        sites = {Path(sysconfig.get_path(key)).resolve()
                 for key in ("purelib", "platlib")}
        cls.modules = {}
        for name in ("lipi", "lipi.cli", "lipi.checker.model"):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
            if not any(path.is_relative_to(site) for site in sites):
                raise AssertionError("%s загружен вне site-packages: %s" % (name, path))
            if any(path.is_relative_to(root) for root in (cls.source, checkout)):
                raise AssertionError("%s загружен из исходников: %s" % (name, path))
            relative = Path(*name.split("."))
            relative = relative / "__init__.py" if name == "lipi" else relative.with_suffix(".py")
            if path != Path(cls.dist.locate_file(relative)).resolve():
                raise AssertionError("Импорт %s не принадлежит установленному distribution" % name)
            cls.modules[name] = module
        cls.shared = (Path(sysconfig.get_path("data")) / "share" / "lipi").resolve()
        if any(cls.shared.is_relative_to(root) for root in (cls.source, checkout)):
            raise AssertionError("share/lipi должен находиться вне исходников")
        cls.expected = {Path(name) for name in ("README.md", "SETUP.md", "CHANGELOG.md")}
        cls.expected.update(CONTRIBUTOR_GUIDES)
        cls.expected.update(path.relative_to(cls.source)
                            for path in (cls.source / "docs").rglob("*.md"))
        for edition in EDITIONS:
            index = edition / "README.md"
            if index not in cls.expected:
                raise AssertionError("В --source отсутствует оглавление %s" % index)
        cls.assets = {path.relative_to(cls.source)
                      for path in (cls.source / ASSETS).rglob("*") if path.is_file()}

    def test_installed_version_and_entrypoint(self):
        tree = ast.parse((self.source / "src/lipi/__init__.py").read_text(encoding="utf-8"))
        versions = [ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "__version__"
                            for target in node.targets)]
        self.assertEqual(len(versions), 1)
        self.assertEqual(self.modules["lipi"].__version__, versions[0])
        self.assertEqual(self.modules["lipi.cli"].VERSION, versions[0])
        self.assertEqual(self.dist.version, versions[0])
        entries = [(entry.name, entry.value) for entry in self.dist.entry_points
                   if entry.group == "console_scripts"]
        self.assertEqual(entries, [("lipi", "lipi.cli:main")])

    def test_complete_document_tree_and_loader(self):
        actual = {path.relative_to(self.shared) for path in self.shared.rglob("*.md")}
        self.assertEqual(actual, self.expected)
        for relative in sorted(self.expected):
            with self.subTest(page=relative.as_posix()):
                installed = self.shared / relative
                self.assertEqual(installed.read_bytes(), (self.source / relative).read_bytes())
                loaded = self.modules["lipi.cli"].packaged_doc(relative.as_posix())
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.resolve(), installed.resolve())
                self.assertTrue(loaded.resolve().is_relative_to(self.shared))

    def test_interface_resources(self):
        source = self.source / "src/lipi/locale"
        installed = Path(self.modules["lipi"].__file__).parent / "locale"
        def contents(directory):
            return {p.relative_to(directory): p.read_bytes()
                    for p in directory.rglob("*") if p.is_file()}
        self.assertEqual(contents(installed), contents(source))

    def test_document_assets(self):
        actual = {path.relative_to(self.shared)
                  for path in (self.shared / ASSETS).rglob("*") if path.is_file()}
        self.assertEqual(actual, self.assets)
        for relative in sorted(self.assets):
            with self.subTest(asset=relative.as_posix()):
                self.assertTrue((self.shared / relative).read_bytes() ==
                                (self.source / relative).read_bytes(),
                                "Содержимое установленного ресурса отличается от --source")

    def test_guide_from_installed_command(self):
        command = Path(sysconfig.get_path("scripts")) / ("lipi.exe" if os.name == "nt" else "lipi")
        self.assertTrue(command.is_file(), str(command))
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONIOENCODING"] = "utf-8"
        with tempfile.TemporaryDirectory(prefix="lipi-installed-guide-") as cwd:
            result = subprocess.run([str(command), "guide"], cwd=cwd, env=env,
                                    capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        expected = (self.source / "SETUP.md").read_text(encoding="utf-8").rstrip() + "\n"
        self.assertEqual(result.stdout.decode("utf-8").replace("\r\n", "\n"), expected)

    def test_links_between_installed_pages(self):
        model = self.modules["lipi.checker.model"]
        pages = {relative: model.Page(self.shared / relative,
                                     (self.shared / relative).read_text(encoding="utf-8"))
                 for relative in self.expected}
        en, ru = EDITIONS
        en_pages = {p.relative_to(en) for p in pages if p.is_relative_to(en)}
        ru_pages = {p.relative_to(ru) for p in pages if p.is_relative_to(ru)}
        self.assertEqual(en_pages, ru_pages)
        for relative in sorted(en_pages):
            with self.subTest(anchors=relative.as_posix()):
                self.assertEqual(set(pages[en / relative].anchors), set(pages[ru / relative].anchors))

        entry_links = {(Path(page), edition / "README.md")
                       for page in ("README.md", "SETUP.md") for edition in EDITIONS}
        entry_links.add((Path("README.md"), CONTRIBUTOR_GUIDES[0]))
        entry_links.update((edition / "README.md", guide)
                           for edition, guide in zip(EDITIONS, CONTRIBUTOR_GUIDES))
        edition_checks = dict.fromkeys(EDITIONS, 0)
        page_names = {relative.name for relative in self.expected}
        checked = external = outside = 0
        logo_in_readme = False
        for relative, page in sorted(pages.items()):
            self.assertIsNone(re.search(r"^\s{0,3}\[[^\]]+\]:", page.masked, re.M),
                              "%s: reference definitions требуют расширения smoke-теста" % relative)
            for line, target, is_image in document_links(page, model):
                with self.subTest(page=relative.as_posix(), line=line, target=target):
                    uri = urlsplit(target)
                    if uri.scheme or uri.netloc:
                        external += 1
                        continue
                    source_target = ((self.source / relative).parent / unquote(uri.path)).resolve() \
                        if uri.path else self.source / relative
                    if not source_target.is_relative_to(self.source):
                        self.assertFalse(is_image, "Путь изображения выходит за корень описания")
                        self.assertNotIn(source_target.name, page_names,
                                         "Ссылка на имя страницы описания выходит за корень")
                        outside += 1
                        continue
                    destination = source_target.relative_to(self.source)
                    if is_image:
                        self.assertIn(destination, self.assets,
                                      "Изображение отсутствует среди ресурсов описания")
                    if destination in self.assets:
                        resolved = (page.path.parent / unquote(uri.path)).resolve()
                        self.assertEqual(resolved, self.shared / destination)
                        self.assertTrue(resolved.is_file(), "Ресурс отсутствует в установке: %s" % resolved)
                        if (is_image and relative == Path("README.md")
                                and destination == LOGO):
                            logo_in_readme = True
                        checked += 1
                        continue
                    # Root Markdown and docs/ are the description namespace.
                    # AGENTS.md belongs to executor rules and is not shipped here.
                    description = (destination in self.expected
                                   or destination.parts[:1] == ("docs",)
                                   or (destination.parent == Path(".")
                                       and destination.suffix == ".md"
                                       and destination.name != "AGENTS.md"))
                    if not description:
                        outside += 1
                        continue
                    self.assertIn(destination, self.expected, "Ссылка на отсутствующую страницу описания")
                    resolved, anchor = model.resolve_target(page, target)
                    self.assertEqual(resolved, (self.shared / destination).resolve())
                    if anchor:
                        self.assertIn(anchor, pages[destination].anchors.keys() | pages[destination].slugs.keys())
                    entry_links.discard((relative, destination))
                    for edition in EDITIONS:
                        if relative.is_relative_to(edition):
                            edition_checks[edition] += 1
                    checked += 1
        self.assertTrue(logo_in_readme, "README.md не ссылается на %s как на изображение" % LOGO)
        self.assertFalse(entry_links, "Отсутствуют ссылки между точками входа: %s" % entry_links)
        for edition, count in edition_checks.items():
            self.assertGreater(count, 0, "Нет ссылок между страницами из %s" % edition)
        print("\nСсылки и изображения: проверено %d (из docs/en: %d, из docs/ru: %d); "
              "вне поставленного описания %d; внешние URI %d (последние две группы не проверялись)."
              % (checked, edition_checks[en], edition_checks[ru], outside, external), file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="снимок исходников той же ревизии: ожидаемые страницы, ресурсы и версия")
    args = parser.parse_args()
    SOURCE = args.source.resolve()
    unittest.main(argv=[sys.argv[0]], verbosity=2)
