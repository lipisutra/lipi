"""Единый init: первое подключение и повторное применение (ADR-014).

Файлы проекта и baseline сохраняются; managed-файлы повторно применяются
из установленного пакета. Отказы и dry-run не меняют дерево проекта.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests import support
from tests.support import localized
from lipi import i18n

VERSION = support.VERSION
TYPE_DIRS = ("plan", "issue", "discussion", "adr", "audit")
# файлы lipi (ADR-009): только они попадают в .agents/lipi/ и в lock;
# копии чекера в проекте нет (ADR-010) — её запись LIPI_FILES не содержит
LIPI_FILES = (".agents/lipi/README.md", ".agents/lipi/documentation.md",
              ".agents/lipi/workflow.md")
# заготовки проекта: init их создаёт, повторный init не трогает, в lock они не входят
SEED_FILES = ("docs/README.md", "AGENTS.md", "workflow/README.md",
              "workflow/masterplan.md")
# строка в AGENTS.md, по которой V2 узнаёт ссылку на правила lipi
AGENTS_LINK = "](.agents/lipi/README.md)"


def init_module():
    """Модуль lipi.init в процессе теста: шаблоны можно подменить."""
    src = str(support.LIPI / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from lipi import init as module
    return module


def fake_templates(tmp):
    """Копия текущих шаблонов, которую тест может править."""
    templates = Path(tmp) / "templates"
    shutil.copytree(support.SRC / "locale" / "en" / "templates", templates,
                    ignore=shutil.ignore_patterns("__pycache__"))
    return templates


def rendered(init, root, templates=None):
    """Отрисованные шаблоны: {путь в проекте: текст}."""
    cfg = json.loads((root / "lipi.json").read_text(encoding="utf-8"))
    kind = "app" if cfg.get("description") else "package"
    files, _ = init.render(root, kind, cfg.get("docs") or "docs",
                           cfg.get("workflow") or "workflow", templates=templates)
    return {init.rel_name(root, p): text for p, text in files.items()}


def set_lock_version(root, version):
    """Версия в lock-файле проекта (шаблоны при этом не меняются)."""
    path = root / support.LOCK_REL
    lock = json.loads(path.read_text(encoding="utf-8"))
    lock["lipi"] = version
    support.w(path, json.dumps(lock, sort_keys=True, indent=2) + "\n")


def run_init(module, root, templates=None, dry_run=False):
    """initialize() с отдельными шаблонами: (код, вывод)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = module.initialize(root, templates=templates, dry_run=dry_run)
    return code, out.getvalue()


def tree(root):
    """Снимок дерева проекта: {путь: байты} — сравнение «до и после»."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def digest_text(text):
    """sha256 отрисованного шаблона так, как он окажется в файле.

    Файлы пишутся в текстовом режиме: на Windows «\\n» становится CRLF.
    """
    data = text.encode("utf-8")
    if os.linesep != "\n":
        data = data.replace(b"\n", os.linesep.encode("utf-8"))
    return hashlib.sha256(data).hexdigest()


def sha256_path(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# @trace docs/ru/commands.md#update,ADR-014
class InitTest(unittest.TestCase):
    """init.py: развёртывание каркаса и команда lipi init."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-init-"))
        self.root = (self.tmp / "root").resolve()
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self):
        """Настройки проекта из lipi.json."""
        return json.loads((self.root / "lipi.json").read_text(encoding="utf-8"))

    def lock(self):
        """Lock-файл проекта из .agents/lipi/lipi.lock."""
        return json.loads((self.root / support.LOCK_REL).read_text(encoding="utf-8"))

    def test_package_skeleton(self):
        """Пакетный каркас: файлы lipi, заготовки, настройки, lock и чистая проверка."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        # файлы lipi и заготовки: .agents/README.md и .agents/documentation.md
        # проект lipi больше не создаёт (ADR-009)
        for rel in LIPI_FILES + (".agents/lipi/lipi.lock",) + SEED_FILES \
                + ("workflow/INDEX.md",):
            self.assertTrue((self.root / rel).is_file(), rel)
        for rel in (".agents/README.md", ".agents/documentation.md",
                    ".agents/tools/check.py", ".agents/lipi.lock",
                    support.CHECK_REL):
            self.assertFalse((self.root / rel).exists(), rel)
        for d in TYPE_DIRS:
            self.assertTrue((self.root / "workflow" / d).is_dir(), d)
        cfg = self.config()
        self.assertNotIn("lipi", cfg)
        self.assertEqual(cfg["docs"], "docs")
        self.assertEqual(cfg["workflow"], "workflow")
        # AGENTS.md: ссылка на правила lipi (V2); workflow/README.md: указатель
        # на правила рабочих материалов вместо их текста
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(AGENTS_LINK, agents)
        self.assertGreaterEqual(agents.count(AGENTS_LINK), 1)
        workflow_readme = (self.root / "workflow" / "README.md").read_text(encoding="utf-8")
        self.assertIn("](../.agents/lipi/workflow.md)", workflow_readme)
        # сама заготовка короткая: правила типов живут в .agents/lipi/workflow.md
        self.assertNotIn('<a id="types">', workflow_readme)
        workflow_rules = (self.root / ".agents" / "lipi" / "workflow.md").read_text(
            encoding="utf-8")
        self.assertIn('<a id="types">', workflow_rules)
        # lock: версия и отпечатки ТОЛЬКО правил lipi; копии чекера нет
        lock = self.lock()
        self.assertEqual(lock["lipi"], VERSION)
        self.assertEqual(set(lock["files"]), set(LIPI_FILES))
        for rel in LIPI_FILES:
            self.assertEqual(lock["files"][rel],
                             hashlib.sha256((self.root / rel).read_bytes()).hexdigest(), rel)
        # заготовки и файлы, не созданные из шаблонов, в lock не входят
        for rel in SEED_FILES + ("lipi.json", "workflow/INDEX.md"):
            self.assertNotIn(rel, lock["files"])
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('errors: 0, warnings: 0', "ошибок: 0, предупреждений: 0"), out)
        # в выводе init нет ни копии чекера, ни пути к ней
        self.assertNotIn("check.py", out)
        self.assertNotIn(localized('checker copy', "копия чекера"), out)

    def test_no_checker_copy(self):
        """init в пустой папке: копии чекера нет и в lock её записи нет."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertFalse((self.root / support.CHECK_REL).exists())
        self.assertNotIn(support.CHECK_REL, self.lock()["files"])
        self.assertEqual(set(self.lock()["files"]), set(LIPI_FILES))
        self.assertIn(localized('Run lipi check to verify', "Проверка: lipi check"), out)
        self.assertNotIn("check.py", out)
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('errors: 0, warnings: 0', "ошибок: 0, предупреждений: 0"), out)

    def test_init_twice_keeps_existing_files(self):
        """Повторный init называет версию правил, lock не меняется."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        first_lock = self.lock()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(VERSION, out)
        self.assertNotIn(localized('created', "создан"), out)
        self.assertEqual(self.lock(), first_lock)

    def test_app_type(self):
        """--type app: описание разработчика в docs/development и чистая проверка."""
        code, out = support.init(self.root, "--type", "app")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.config()["description"], "docs/development")
        self.assertTrue((self.root / "docs" / "development" / "README.md").is_file())
        # раздел про справку — в документации lipi, а не в заготовке
        doc = (self.root / ".agents" / "lipi" / "documentation.md").read_text(encoding="utf-8")
        self.assertIn("User help and system documentation", doc)
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)

    def test_custom_docs_and_workflow(self):
        """--docs и --workflow создают каркас в своих каталогах проекта."""
        code, out = support.init(self.root, "--docs", "documentation", "--workflow", "work")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "documentation" / "README.md").is_file())
        self.assertTrue((self.root / "work" / "README.md").is_file())
        cfg = self.config()
        self.assertEqual(cfg["docs"], "documentation")
        self.assertEqual(cfg["workflow"], "work")
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)

    def test_seed_paths_inside_managed_directory_stay_project_owned(self):
        docs = support.LIPI_DIR
        workflow = docs + "/work"
        code, out = support.init(self.root, "--docs", docs, "--workflow", workflow)
        self.assertEqual(code, 0, out)
        self.assertEqual(set(self.lock()["files"]), set(LIPI_FILES))
        rules = self.root / docs / "README.md"
        self.assertTrue(rules.read_text(encoding="utf-8").startswith("# lipi rules\n"))
        for name in ("README.md", "masterplan.md"):
            self.assertTrue((self.root / workflow / name).is_file())
        masterplan = self.root / workflow / "masterplan.md"
        original = masterplan.read_bytes()
        masterplan.write_bytes(original + b"\nProject notes.\n")
        lock = self.lock()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lock(), lock)
        self.assertEqual(masterplan.read_bytes(), original + b"\nProject notes.\n")

    def test_external_workflow_refuses_before_any_writes(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    support.w(self.tmp / "wf" / "note.md", "# Рабочие материалы\n")
                before = snapshot(self.tmp)
                code, out = support.init(self.root, "--workflow", "../wf")
                self.assertEqual(code, 2, out)
                self.assertIn(localized('External workflow', "внешний workflow"), out)
                self.assertEqual(snapshot(self.tmp), before)

    def test_init_creates_empty_baseline(self):
        """init в пустой папке: пустая базовая линия, проверка 0/0."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        baseline = json.loads((self.root / support.BASE_REL)
                              .read_text(encoding="utf-8"))
        self.assertEqual(baseline, {"schema": 1, "entries": []})
        self.assertIn(localized('Baseline', "базовая линия"), out)
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('errors: 0, warnings: 0', "ошибок: 0, предупреждений: 0"), out)

    def test_existing_project_baseline_preserves_files(self):
        """Существующий проект: долг в базовой линии, пользовательские файлы целы."""
        docs = ("# Старое\n\n## Раздел\n\n[к разделу](#раздел) [битая](net.md)\n"
                + "строка\n" * 400)
        support.w(self.root / "docs" / "README.md", docs)
        plan = self.root / "workflow" / "current" / "plan-old.md"
        support.w(plan, "# Старый план\n")
        support.w(self.root / "AGENTS.md", "мои правила\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        # Существующая заготовка остаётся побайтно прежней.
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents, "мои правила\n")
        # чужие файлы не изменены
        self.assertEqual((self.root / "docs" / "README.md").read_text(encoding="utf-8"),
                         docs)
        self.assertEqual(plan.read_text(encoding="utf-8"), "# Старый план\n")
        self.assertFalse((self.root / "workflow" / "README.md").exists())
        # старые рабочие материалы: их проверка отключена, есть подсказка migrate
        cfg = self.config()
        self.assertNotIn("anchors", cfg)
        self.assertNotIn("lipi", cfg)
        # ослабленных настроек больше нет: правила действуют в полную силу
        self.assertNotIn("limits", cfg)
        self.assertIsNone(cfg["workflow"])
        self.assertIn("lipi migrate", out)
        # lock создан (с отпечатками правил), а оставленный чужой AGENTS.md в
        # отпечатки не записан
        lock = self.lock()
        self.assertEqual(lock["lipi"], VERSION)
        self.assertEqual(set(lock["files"]), set(LIPI_FILES))
        self.assertNotIn("AGENTS.md", lock["files"])
        # Базовая линия покрывает прежние ошибки описания. V2 остаётся видимой.
        baseline = json.loads((self.root / support.BASE_REL)
                              .read_text(encoding="utf-8"))
        self.assertEqual(baseline["schema"], 1)
        self.assertEqual(sum(e["count"] for e in baseline["entries"]), 3)
        self.assertIn(localized('Baseline', "базовая линия"), out)
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)
        self.assertIn(localized('in the baseline: 3, fixed: 0', "в базовой линии 3, исправлено 0"), out)
        code, out = support.check(self.root, "--no-baseline")
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "D1"), out)

    def test_foreign_workflow_is_not_checked(self):
        """Старые рабочие материалы: workflow null, документы не проверяются."""
        support.w(self.root / "workflow" / "completed" / "plan-old.md",
                  "# Старый план\n\nбез шапки\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.config()["workflow"])
        self.assertIn("lipi migrate", out)
        # Подсказка — точная команда с найденным каталогом
        self.assertIn("lipi migrate workflow", out)
        self.assertFalse((self.root / "workflow" / "INDEX.md").exists())
        self.assertFalse((self.root / "workflow" / "plan").exists())
        self.assertEqual((self.root / "workflow" / "completed" / "plan-old.md")
                         .read_text(encoding="utf-8"),
                         "# Старый план\n\nбез шапки\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn("plan-old.md", out)
        # Подсказка init — рабочая команда, выполняется без ошибки
        support.git_init(self.root)
        support.commit(self.root, "init")
        code, out = support.cli(self.root, "migrate", "workflow")
        self.assertEqual(code, 0, out)

    def test_ignored_foreign_workflow_does_not_disable_workflow(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                repo = self.tmp / ("nested-repository" if nested else "repository")
                project = repo / "project" if nested else repo
                project.mkdir(parents=True)
                support.git_init(repo)
                support.w(project / ".gitignore", "/workflow/current/\n")
                support.commit(repo, "initial")
                old = project / "workflow/current/old.md"
                support.w(old, "# Ignored old document\n")
                code, out = support.init(project)
                self.assertEqual(code, 0, out)
                cfg = json.loads((project / "lipi.json").read_text(encoding="utf-8"))
                self.assertEqual(cfg["workflow"], "workflow")
                self.assertTrue((project / "workflow/README.md").is_file())
                self.assertEqual(old.read_text(encoding="utf-8"), "# Ignored old document\n")

    def test_init_rejects_ignored_workflow_symlink_without_resolving(self):
        support.git_init(self.root)
        support.w(self.root / ".gitignore", "/workflow\n")
        support.commit(self.root, "initial")
        peer = self.tmp / "peer"
        peer.mkdir()
        link = self.root / "workflow"
        link.symlink_to(peer, target_is_directory=True)
        original = Path.readlink

        def readlink(path):
            if path == link:
                self.fail("ignored workflow symlink was resolved")
            return original(path)

        with mock.patch.object(Path, "readlink", readlink):
            code, out = run_init(init_module(), self.root)
        self.assertEqual(code, 2, out)
        self.assertIn(localized('Symlink', "символическая ссылка"), out)
        self.assertEqual(list(peer.iterdir()), [])
        self.assertFalse((self.root / "lipi.json").exists())

    def test_unknown_keys_are_rejected(self):
        """Ключи вне контракта lipi init дают код 2."""
        for key in ("--adopt", "--update", "--hook"):
            code, out = support.init(self.root, key)
            self.assertEqual(code, 2, (key, out))
            self.assertIn(localized("unrecognized arguments", "неизвестные аргументы"), out, (key, out))
        code, out = support.run(support.PY + [str(support.INIT), "--help"])
        self.assertEqual(code, 0, out)
        for key in ("--adopt", "--update", "--hook"):
            self.assertNotIn(key, out)

    def test_reapply_after_init_keeps_workflow_links_out(self):
        """init: повторный init не возвращает ссылки на чужие рабочие материалы."""
        support.w(self.root / "docs" / "README.md",
                  "# Мой проект\n\n## Раздел\n\n[к разделу](#раздел)\n")
        support.w(self.root / "workflow" / "plan-old.md", "# Старый план\n")
        support.w(self.root / "AGENTS.md", "мои правила\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        agents_after_init = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        rules = (self.root / ".agents" / "lipi" / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("workflow/README.md", rules)
        # Повторное применение не добавляет ссылку в пользовательский файл.
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"),
                         agents_after_init)
        self.assertEqual(agents_after_init, "мои правила\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)
        self.assertFalse(support.found(out, "W6"), out)

    def test_cli_init_dry_run(self):
        """lipi init --dry-run проходит через команду и ничего не меняет."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        before = tree(self.root)
        code, out = support.cli(self.root, "init", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("dry-run", out)
        self.assertEqual(tree(self.root), before)

    def test_cli_init_path_and_dry_run(self):
        """lipi init <папка> --dry-run передаёт и каталог, и ключ."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        before = tree(self.root)
        code, out = support.cli(self.tmp, "init", str(self.root), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("dry-run", out)
        self.assertEqual(tree(self.root), before)

    def test_version(self):
        """--version чекера в проекте и в самом lipi печатает версию."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        code, out = support.check(self.root, "--version")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("lipi "), out)
        code, out = support.run(support.PY + [str(support.CHECK), "--version"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), "lipi %s" % VERSION)


class ManagedFilesTest(unittest.TestCase):
    """повторный init заменяет файлы lipi целиком, независимо от правок проекта."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-reapply-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.init = init_module()
        self.templates = fake_templates(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lock(self):
        return json.loads((self.root / support.LOCK_REL).read_text(encoding="utf-8"))

    def edit(self, path, old, new):
        """Заменяет текст в файле шаблона новой версии."""
        text = path.read_text(encoding="utf-8")
        assert old in text, "%s: нет «%s»" % (path, old)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_modified_lipi_file_is_replaced(self):
        """Изменённый проектом файл lipi заменяется новой версией шаблона."""
        name = "lipi/common/README.md"
        self.edit(self.templates / name, "# lipi rules", "# lipi rules (new edition)")
        target = self.root / support.LIPI_DIR / "README.md"
        support.w(target, "# Правила проекта\n\nсвои правила\n")
        fresh = rendered(self.init, self.root, self.templates)
        code, out = run_init(self.init, self.root, self.templates)
        self.assertEqual(code, 0, out)
        self.assertIn(".agents/lipi/README.md", out)
        self.assertIn(localized('Applied rules from lipi %s', "правила проекта применены из установленного lipi %s") % VERSION,
                      out)
        self.assertEqual(target.read_text(encoding="utf-8"),
                         fresh[".agents/lipi/README.md"])
        self.assertIn("(new edition)", target.read_text(encoding="utf-8"))

    def test_untouched_lipi_file_is_replaced(self):
        """Нетронутый файл lipi тоже заменяется новой версией шаблона."""
        self.edit(self.templates / "lipi" / "common" / "workflow.md",
                  "# Workflow documents", "# Workflow documents (new edition)")
        fresh = rendered(self.init, self.root, self.templates)
        code, out = run_init(self.init, self.root, self.templates)
        self.assertEqual(code, 0, out)
        self.assertIn(".agents/lipi/workflow.md", out)
        self.assertEqual((self.root / support.LIPI_DIR / "workflow.md")
                         .read_text(encoding="utf-8"),
                         fresh[".agents/lipi/workflow.md"])

    def test_deleted_lipi_file_is_created_again(self):
        """Удалённый проектом файл lipi создаётся заново из шаблона."""
        deleted = self.root / support.LIPI_DIR / "documentation.md"
        deleted.unlink()
        code, out = run_init(self.init, self.root, self.templates)
        self.assertEqual(code, 0, out)
        self.assertIn(".agents/lipi/documentation.md", out)
        self.assertTrue(deleted.is_file())

    def test_lock_digests_are_from_templates(self):
        """В lock — отпечатки отрисованных шаблонов, без копии чекера."""
        self.edit(self.templates / "lipi" / "common" / "README.md",
                  "# lipi rules", "# lipi rules (new edition)")
        support.w(self.root / support.LIPI_DIR / "README.md", "# чужая правка\n")
        fresh = rendered(self.init, self.root, self.templates)
        code, out = run_init(self.init, self.root, self.templates)
        self.assertEqual(code, 0, out)
        lock = self.lock()
        self.assertEqual(lock["lipi"], VERSION)
        self.assertEqual(set(lock["files"]), set(LIPI_FILES))
        for name in LIPI_FILES:
            self.assertEqual(lock["files"][name], digest_text(fresh[name]), name)
        for name in LIPI_FILES:
            self.assertEqual(lock["files"][name], sha256_path(self.root / name), name)

    def test_removed_template_file_is_listed_and_kept(self):
        """Файл, удалённый из шаблонов lipi, перечисляется, но остаётся в проекте."""
        self.assertTrue((self.root / support.LIPI_DIR / "documentation.md").is_file())
        (self.templates / "lipi" / "common" / "documentation.md").unlink()
        code, out = run_init(self.init, self.root, self.templates)
        self.assertEqual(code, 0, out)
        self.assertIn(localized('Templates removed from lipi (existing files kept):', "удалены из шаблонов lipi (файлы оставлены):"), out)
        self.assertIn("  .agents/lipi/documentation.md", out)
        self.assertTrue((self.root / support.LIPI_DIR / "documentation.md").is_file())
        self.assertNotIn(".agents/lipi/documentation.md", self.lock()["files"])

    def test_dry_run_changes_nothing(self):
        """--dry-run показывает то же, что повторный init, но не меняет ни одного файла."""
        self.edit(self.templates / "lipi" / "common" / "workflow.md",
                  "# Workflow documents", "# Workflow documents (new edition)")
        support.w(self.root / support.LIPI_DIR / "README.md", "# Правила проекта\n")
        before = tree(self.root)
        code, out = run_init(self.init, self.root, self.templates, dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertIn(VERSION, out)
        self.assertIn(localized('dry-run: no changes made', "dry-run: ничего не изменено"), out)
        self.assertNotIn(localized('Applied rules', "правила проекта применены"), out)
        self.assertIn(".agents/lipi/workflow.md", out)
        self.assertIn(".agents/lipi/README.md", out)
        self.assertEqual(tree(self.root), before)


class LocalizedTemplatesTest(unittest.TestCase):
    def test_managed_templates_and_lock_are_independent_of_interface_language(self):
        with tempfile.TemporaryDirectory(prefix="lipi-init-language-") as directory:
            base = Path(directory)
            managed = LIPI_FILES + (support.CI_REL, support.LOCK_REL)
            seeds_and_state = SEED_FILES + ("docs/development/README.md", "lipi.json",
                                             support.BASE_REL)
            first_deployments = {}
            for first, second, seed_title in (("ru", "en", "# Точки входа"),
                                              ("en", "ru", "# Where to start")):
                with self.subTest(first=first, second=second):
                    root = base / first
                    root.mkdir()
                    support.git_init(root)
                    env = support.language_env(base / (first + "-profile"), first)

                    def cli(*args):
                        code, out = support.run(support.PY + [str(support.CLI), *args],
                                                cwd=root, env=env)
                        self.assertEqual(code, 0, out)
                        return out

                    out = cli("init", "--type", "app", "--ci", "github", "--enforce")
                    self.assertIn(i18n.tr("init.summary", first) % VERSION, out)
                    self.assertTrue((root / "AGENTS.md").read_text(encoding="utf-8")
                                    .startswith(seed_title))
                    self.assertIn("lipi check --staged",
                                  (root / ".git/hooks/pre-commit").read_text(encoding="utf-8"))
                    self.assertNotIn("\n        continue-on-error:",
                                     (root / support.CI_REL).read_text(encoding="utf-8"))
                    lock = json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))
                    self.assertIs(lock["enforce"], True)
                    self.assertEqual(lock["files"], {name: sha256_path(root / name)
                                                    for name in managed if name != support.LOCK_REL})

                    stable_paths = managed + seeds_and_state
                    for name in stable_paths:
                        os.utime(root / name, (1_600_000_000, 1_600_000_000))
                    before = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns)
                              for name in stable_paths}
                    first_deployments[first] = {name: before[name][0] for name in managed}

                    cli("lang", second)
                    self.assertNotIn("V3]", cli("check"))
                    out = cli("init")
                    self.assertIn(i18n.tr("init.summary", second) % VERSION, out)
                    self.assertNotIn(i18n.tr("init.summary", first) % VERSION, out)
                    for name, (content, mtime) in before.items():
                        self.assertEqual((root / name).read_bytes(), content, name)
                        self.assertEqual((root / name).stat().st_mtime_ns, mtime, name)

                    out = cli("ci", "github")
                    self.assertIn(i18n.tr("init.ci_summary", second) % VERSION, out)
                    for name in (support.CI_REL, support.LOCK_REL):
                        self.assertEqual((root / name).read_bytes(), before[name][0], name)
                        self.assertEqual((root / name).stat().st_mtime_ns, before[name][1], name)

                    ci_file = root / support.CI_REL
                    ci_file.unlink()
                    cli("ci", "github")
                    self.assertEqual(ci_file.read_bytes(), before[support.CI_REL][0])
                    self.assertEqual((root / support.LOCK_REL).stat().st_mtime_ns,
                                     before[support.LOCK_REL][1])
                    self.assertNotIn("V3]", cli("check"))
            self.assertEqual(set(first_deployments), {"en", "ru"})
            self.assertEqual(first_deployments["ru"], first_deployments["en"])

    def test_existing_russian_managed_files_are_replaced_by_canonical_files(self):
        with tempfile.TemporaryDirectory(prefix="lipi-init-legacy-language-") as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            env = support.language_env(base / "profile", "ru")

            def cli(*args):
                code, out = support.run(support.PY + [str(support.CLI), *args],
                                        cwd=root, env=env)
                self.assertEqual(code, 0, out)
                return out

            cli("init", "--ci", "github")
            self.assertTrue((root / "AGENTS.md").read_text(encoding="utf-8")
                            .startswith("# Точки входа"))
            cli("lang", "en")
            cli("init")
            managed = LIPI_FILES + (support.CI_REL, support.LOCK_REL)
            canonical = {name: (root / name).read_bytes() for name in managed}
            old_templates = {
                LIPI_FILES[0]: "# Правила lipi",
                LIPI_FILES[1]: "# Правила описания проекта",
                LIPI_FILES[2]: "# Рабочие материалы",
                support.CI_REL: "# Задание CI: установленный lipi проверяет проект.",
            }
            for name, first_line in old_templates.items():
                path = root / name
                _, rest = path.read_text(encoding="utf-8").split("\n", 1)
                support.w(path, first_line + "\n" + rest)
            lock_path = root / support.LOCK_REL
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["files"] = {name: sha256_path(root / name) for name in old_templates}
            support.w(lock_path, json.dumps(lock, sort_keys=True, indent=2) + "\n")
            stable_paths = SEED_FILES + ("lipi.json", support.BASE_REL)
            stable = {name: (root / name).read_bytes() for name in stable_paths}
            cli("lang", "ru")
            self.assertNotIn("V3]", cli("check"))
            out = cli("init")
            for name in old_templates:
                self.assertNotIn(i18n.tr("init.replaced", "ru") % name, out)
            self.assertEqual({name: (root / name).read_bytes() for name in managed}, canonical)
            self.assertEqual({name: (root / name).read_bytes() for name in stable_paths}, stable)
            self.assertNotIn("V3]", cli("check"))

    def test_missing_seed_translation_uses_english_only_for_that_file(self):
        init = init_module()

        with tempfile.TemporaryDirectory(prefix="lipi-init-fallback-") as directory:
            root = Path(directory).resolve()
            locale = root / "locale"
            shutil.copytree(i18n.LOCALE, locale)
            (locale / "ru/templates/seed/package/docs/README.md").unlink()

            with mock.patch.object(i18n, "LOCALE", locale):
                english, _ = init.render(root, "package", "docs", "workflow", language="en")
                russian, _ = init.render(root, "package", "docs", "workflow", language="ru")

            self.assertEqual(english.keys(), russian.keys())
            self.assertEqual(russian[root / "docs/README.md"], english[root / "docs/README.md"])
            self.assertTrue(russian[root / "AGENTS.md"].startswith("# Точки входа"))


class SeedsTest(unittest.TestCase):
    """повторный init не трогает заготовки проекта, в том числе отсутствующие."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-seeds-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.init = init_module()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_seed_is_not_created(self):
        """Отсутствующая заготовка не создаётся заново."""
        for rel in ("docs/README.md", "workflow/masterplan.md", "AGENTS.md"):
            (self.root / rel).unlink()
        code, out = run_init(self.init, self.root)
        self.assertEqual(code, 0, out)
        for rel in ("docs/README.md", "workflow/masterplan.md", "AGENTS.md"):
            self.assertFalse((self.root / rel).exists(), rel)
            self.assertNotIn(localized('created:   %s', "создан:    %s") % rel, out)
        # обновление всё же состоялось: lock новой версии
        self.assertEqual(json.loads((self.root / support.LOCK_REL)
                                    .read_text(encoding="utf-8"))["lipi"], VERSION)

    def test_changed_seed_is_kept(self):
        """Изменённая заготовка остаётся как есть."""
        agents = self.root / "AGENTS.md"
        support.w(agents, agents.read_text(encoding="utf-8") + "\nмоя строка\n")
        docs = self.root / "docs" / "README.md"
        support.w(docs, docs.read_text(encoding="utf-8") + "\nмоя строка\n")
        before = agents.read_bytes(), docs.read_bytes()
        code, out = run_init(self.init, self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual((agents.read_bytes(), docs.read_bytes()), before)
        self.assertNotIn(localized('kept:      AGENTS.md', "оставлен:  AGENTS.md"), out)
        self.assertNotIn(localized('kept:      docs/README.md', "оставлен:  docs/README.md"), out)


def snapshot(root):
    """Байты, состав дерева и mtime; чтение не скрывает лишнюю перезапись."""
    return {p.relative_to(root).as_posix():
            (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
            for p in [root, *sorted(root.rglob("*"))]}


class ApplyContractTest(unittest.TestCase):
    """Матрица первого и повторного применения по ADR-014."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-contract-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def apply(self, *args):
        code, out = support.init(self.root, *args)
        self.assertEqual(code, 0, out)
        return out

    def assert_rejected_without_writes(self, *args):
        before = snapshot(self.tmp)
        code, out = support.init(self.root, *args)
        self.assertEqual(code, 2, out)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertNotIn("Traceback", out)
        return out

    def test_first_with_config_keeps_settings_and_seeds(self):
        cfg = '{ "docs": "manual", "workflow": "work", "enforce": true }\n'
        support.w(self.root / "lipi.json", cfg)
        for name in ("AGENTS.md", "manual/README.md", "work/README.md"):
            support.w(self.root / name, "# Свой файл\n")
        before = {name: (self.root / name).read_bytes()
                  for name in ("lipi.json", "AGENTS.md", "manual/README.md", "work/README.md")}
        self.apply()
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content, name)
        for name in ("work/masterplan.md", "work/plan", "docs", "workflow"):
            self.assertFalse((self.root / name).exists(), name)
        for name in LIPI_FILES:
            self.assertTrue((self.root / name).is_file(), name)
        self.assertTrue((self.root / "work/INDEX.md").is_file())
        self.assertTrue((self.root / "work/index/issues.md").is_file())
        self.assertTrue((self.root / support.BASE_REL).is_file())

    def test_first_with_config_does_not_create_any_seed(self):
        support.w(self.root / "lipi.json", '{}\n')
        self.apply()
        for name in SEED_FILES:
            self.assertFalse((self.root / name).exists(), name)
        self.assertTrue((self.root / "workflow/INDEX.md").is_file())

    def test_first_with_config_refuses_user_index_before_any_writes(self):
        self.apply()
        code, out = support.check(self.root, "new", "pln", "Работа проекта")
        self.assertEqual(code, 0, out)
        (self.root / support.LOCK_REL).unlink()
        (self.root / support.BASE_REL).unlink()
        index = self.root / "workflow/INDEX.md"
        support.w(index, "# Собственный индекс\n\nРучная запись.\n")
        self.assertIn(localized('the index path is occupied by a user file', "путь указателя занят пользовательским файлом"),
                      self.assert_rejected_without_writes())
        self.assertFalse((self.root / support.BASE_REL).exists())
        self.assertFalse((self.root / support.LOCK_REL).exists())

    def test_first_init_path_blockers_are_rejected_before_writes(self):
        cases = (("managed-parent", ".agents", False),
                 ("seed-parent", "docs", False),
                 ("workflow-type", "workflow/plan", False),
                 ("hook", ".git/hooks/pre-commit", True))
        for label, name, directory in cases:
            with self.subTest(path=name):
                self.root = self.tmp / label
                self.root.mkdir()
                target = self.root / name
                if directory:
                    support.git_init(self.root)
                    target.mkdir()
                else:
                    support.w(target, "файл перекрывает каталог\n")
                self.assert_rejected_without_writes("--enforce")

    def test_repeat_managed_directory_is_rejected_before_writes(self):
        self.apply()
        # Первая правка потребовала бы записи раньше заблокированного файла.
        support.w(self.root / LIPI_FILES[0], "# Правка проекта\n")
        blocked = self.root / LIPI_FILES[1]
        blocked.unlink()
        blocked.mkdir()
        self.assert_rejected_without_writes()

    def test_no_lock_preserves_existing_managed_files(self):
        for configured in (False, True):
            with self.subTest(configured=configured):
                root = self.tmp / str(configured)
                root.mkdir()
                if configured:
                    support.w(root / "lipi.json", '{}\n')
                    (root / "docs").mkdir()
                target = root / LIPI_FILES[0]
                support.w(target, "# Свои правила\n")
                before = target.read_bytes(), target.stat().st_mtime_ns
                code, out = support.init(root)
                self.assertEqual(code, 0, out)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
                self.assertTrue((root / LIPI_FILES[1]).is_file())
                code, out = support.check(root, "--no-baseline")
                self.assertTrue(support.found(out, "V3"), out)

    def test_same_version_replaces_each_edited_managed_file(self):
        self.apply()
        expected = {name: (self.root / name).read_bytes() for name in LIPI_FILES}
        for name in LIPI_FILES:
            support.w(self.root / name, "# Правка проекта\n")
        before = snapshot(self.tmp)
        dry = self.apply("--dry-run")
        self.assertEqual(snapshot(self.tmp), before)
        out = self.apply()
        lock = json.loads((self.root / support.LOCK_REL).read_text(encoding="utf-8"))
        for name in LIPI_FILES:
            self.assertIn(localized('Will replace your edits in %s', "ваши правки в %s будут заменены") % name, dry)
            self.assertIn(localized('Replaced your edits in %s', "ваши правки в %s заменены") % name, out)
            self.assertEqual((self.root / name).read_bytes(), expected[name])
            self.assertEqual(lock["files"][name], sha256_path(self.root / name))
        self.assertEqual(lock["lipi"], VERSION)

    def test_lock_repairs_managed_without_restoring_seeds_or_baseline(self):
        self.apply()
        for name in LIPI_FILES + SEED_FILES + ("workflow/INDEX.md", support.BASE_REL):
            (self.root / name).unlink()
        self.apply()
        for name in LIPI_FILES:
            self.assertTrue((self.root / name).is_file(), name)
        for name in SEED_FILES + (support.BASE_REL,):
            self.assertFalse((self.root / name).exists(), name)
        self.assertTrue((self.root / "workflow/INDEX.md").is_file())

    def test_first_and_repeat_preserve_existing_baseline(self):
        baseline = '{ "schema": 1, "entries": [] }\n'
        support.w(self.root / support.BASE_REL, baseline)
        before = (self.root / support.BASE_REL).stat().st_mtime_ns
        self.apply()
        support.w(self.root / "docs/README.md", "# Описание\n\n[битая](missing.md)\n")
        self.apply()
        self.assertEqual((self.root / support.BASE_REL).read_text(encoding="utf-8"), baseline)
        self.assertEqual((self.root / support.BASE_REL).stat().st_mtime_ns, before)

    def test_init_dry_run_without_lock_reports_actual_baseline_action(self):
        self.apply()
        (self.root / support.LOCK_REL).unlink()
        baseline = self.root / support.BASE_REL
        baseline.unlink()
        for exists in (False, True):
            with self.subTest(baseline_exists=exists):
                if exists:
                    support.w(baseline, '{ "schema": 1, "entries": [] }\n')
                before = snapshot(self.tmp)
                dry = self.apply("--dry-run")
                self.assertEqual(snapshot(self.tmp), before)
                creation = localized('Will create baseline: %s', "будет создана базовая линия: %s") % support.BASE_REL
                if exists:
                    self.assertNotIn(creation, dry)
                    self.assertIn(localized('Will keep baseline: %s', "будет сохранена базовая линия: %s") % support.BASE_REL, dry)
                else:
                    self.assertIn(creation, dry)

    def test_noop_preserves_all_mtimes_and_names_installed_version(self):
        support.git_init(self.root)
        self.apply("--enforce", "--ci", "github")
        before = snapshot(self.tmp)
        out = self.apply()
        self.assertEqual(snapshot(self.tmp), before)
        self.assertIn(VERSION, out)

    def test_first_dry_run_writes_nothing_even_for_absent_root(self):
        for exists in (True, False):
            with self.subTest(exists=exists):
                if not exists:
                    self.root.rmdir()
                before = snapshot(self.tmp)
                code, out = support.init(self.root, "--dry-run", "--enforce", "--ci", "github")
                self.assertEqual(code, 0 if exists else 2, out)
                if exists:
                    self.assertIn("dry-run", out)
                self.assertEqual(snapshot(self.tmp), before)

    def test_explicit_conflicts_fail_before_writes(self):
        for deployed in (False, True):
            with self.subTest(deployed=deployed):
                if deployed:
                    self.apply()
                else:
                    support.w(self.root / "lipi.json", '{}\n')
                for args, key in ((("--type", "app"), "description"),
                                  (("--docs", "other"), "docs"),
                                  (("--workflow", "other"), "workflow"),
                                  (("--enforce",), "enforce")):
                    with self.subTest(args=args):
                        out = self.assert_rejected_without_writes(*args)
                        self.assertIn("lipi.json", out)
                        self.assertIn(key, out)

    def test_matching_explicit_args_preserve_existing_config(self):
        args = ("--type", "app", "--docs", "manual", "--workflow", "work", "--enforce")
        self.apply(*args)
        before = snapshot(self.tmp)
        self.apply(*args)
        self.assertEqual(snapshot(self.tmp), before)
        (self.root / support.LOCK_REL).unlink()
        before_cfg = (self.root / "lipi.json").read_bytes()
        self.apply(*args)
        self.assertEqual((self.root / "lipi.json").read_bytes(), before_cfg)

    def test_repeated_init_requires_settings(self):
        self.apply()
        (self.root / "lipi.json").unlink()
        out = self.assert_rejected_without_writes()
        self.assertIn("lipi.json", out)
        self.assertIn(localized('Restore', "восстанов"), out)

    def test_corrupt_config_is_rejected_before_writes(self):
        for text in ('{', '[]', '{"enforce": "yes"}', '{"docs": []}',
                     '{"workflow": 42}', '{"unknown": true}'):
            with self.subTest(config=text):
                support.w(self.root / "lipi.json", text)
                self.assertIn("lipi.json", self.assert_rejected_without_writes())

    def test_corrupt_lock_is_not_treated_as_first_init(self):
        self.apply()
        for text in ('{', '[]', '{}', '{"lipi":"%s","files":[]}' % VERSION,
                     '{"lipi":"invalid","files":{}}',
                     '{"lipi":"%s","files":{"README.md":false}}' % VERSION):
            with self.subTest(lock=text):
                support.w(self.root / support.LOCK_REL, text)
                self.assertIn("lipi.lock", self.assert_rejected_without_writes())

    def test_newer_major_is_rejected_atomically(self):
        self.apply()
        major = int(VERSION.split(".")[0])
        set_lock_version(self.root, "%d.0.0" % (major + 1))
        self.assertIn(localized('Update the installed lipi', "обновите программу"), self.assert_rejected_without_writes())

    def test_existing_version_key_outside_lock_is_rejected(self):
        support.w(self.root / "lipi.json", json.dumps({"lipi": VERSION}))
        self.assertIn(localized('unknown key "lipi"', "неизвестный ключ «lipi»"), self.assert_rejected_without_writes())

    def test_unmanaged_files_are_preserved_with_existing_lock(self):
        self.apply()
        unmanaged = (".agents/local.md", ".agents/tools/local.py",
                     support.LIPI_DIR + "/project-note.md")
        for name in unmanaged:
            support.w(self.root / name, "файл проекта\n")
        before = {name: ((self.root / name).read_bytes(),
                         (self.root / name).stat().st_mtime_ns) for name in unmanaged}
        self.apply()
        for name, expected in before.items():
            path = self.root / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)


if __name__ == "__main__":
    unittest.main()
