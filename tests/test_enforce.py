"""Строгость проекта и хук при первом и повторном init (ADR-011, ADR-014).

Ключ enforce управляет правилами и помеченным хуком lipi. Чужие хуки,
включая старые команды без метки, сохраняются. Код check от enforce не зависит.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support

HOOK_REL = ".git/hooks/pre-commit"
LIPI_MARK = "# lipi"
HOOK_COMMAND = "lipi check --staged"
INSTALL = "pipx install git+https://github.com/lipisutra/lipi"
# тексты правил агента для двух значений enforce (ADR-011)
STRICT = "Fix errors introduced by your change before committing."
SOFT = "Fix or report errors introduced by your change."
UNSET = object()


def init_module():
    """Модуль lipi.init в процессе теста (для render)."""
    src = str(support.SRC.parent)
    if src not in sys.path:
        sys.path.insert(0, src)
    from lipi import init as module
    return module


def deploy(tmp, enforce=UNSET, git=True):
    """Проект с каркасом lipi: (корень, код, вывод init).

    enforce, заданный явно, пишется в lipi.json до init — так выглядит
    существующий проект, который уже выбрал строгость. Без значения проект
    новый: ключа нет, значит false.
    """
    root = tmp / "root"
    root.mkdir()
    if enforce is not UNSET:
        support.w(root / "lipi.json",
                  json.dumps({"enforce": enforce}, ensure_ascii=False) + "\n")
    if git:
        support.git_init(root)
    code, out = support.init(root)
    if code != 0:
        raise AssertionError("init не прошёл: %s" % out)
    return root, code, out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-enforce-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, **kwargs):
        return deploy(self.tmp, **kwargs)[0]

    def hook(self, root):
        return root / HOOK_REL

    def hook_text(self, root):
        return self.hook(root).read_text(encoding="utf-8")

    def rules(self, root):
        return (root / support.LIPI_DIR / "README.md").read_text(encoding="utf-8")

    def lock(self, root):
        return json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))

    def check(self, root):
        return support.check(root)

    def assert_no_hook(self, root):
        self.assertFalse(self.hook(root).exists(),
                         self.hook_text(root) if self.hook(root).is_file() else "")

    def assert_lipi_hook(self, root):
        self.assertTrue(self.hook(root).is_file())
        self.assertTrue(os.access(str(self.hook(root)), os.X_OK))
        text = self.hook_text(root)
        self.assertIn(LIPI_MARK, text)
        self.assertIn(HOOK_COMMAND, text)
        self.assertIn(INSTALL, text)
        # копии чекера в проекте нет (ADR-010): хук зовёт установленную команду
        self.assertNotIn(support.CHECK_REL, text)

    def set_enforce(self, root, value):
        support.set_config(root, enforce=value)


# @trace ADR-011
class InitTest(Base):
    """lipi init: хук и правила агента по enforce."""

    def test_no_key_no_hook(self):
        """Новый проект без ключа: enforce false, хука нет, правила мягкие."""
        root, code, out = deploy(self.tmp)
        self.assert_no_hook(root)
        self.assertNotIn("pre-commit", out)
        self.assertIn(SOFT, self.rules(root))
        self.assertNotIn(STRICT, self.rules(root))
        self.assertIs(self.lock(root)["enforce"], False)

    def test_enforce_true_installs_hook(self):
        """enforce: true в существующем lipi.json — хук lipi check --staged."""
        root, code, out = deploy(self.tmp, enforce=True)
        self.assert_lipi_hook(root)
        self.assertIn(support.localized('created:   %s (lipi)', "создан:    %s (lipi)") % HOOK_REL, out)
        self.assertIn(STRICT, self.rules(root))
        self.assertNotIn(SOFT, self.rules(root))
        self.assertIs(self.lock(root)["enforce"], True)

    def test_enforce_true_without_git(self):
        """enforce: true без .git: хук не ставится, сообщение и код 0."""
        root, code, out = deploy(self.tmp, enforce=True, git=False)
        self.assert_no_hook(root)
        self.assertIn(support.localized('pre-commit hook skipped because the project has no .git directory', "pre-commit не установлен: в проекте нет .git"), out)
        self.assertEqual(code, 0, out)

    def test_foreign_hook_is_not_touched(self):
        """Чужой pre-commit при enforce: true init не трогает и сообщает."""
        root, code, out = deploy(self.tmp)
        foreign = "#!/bin/sh\nexec make lint\n"
        support.w(self.hook(root), foreign)
        self.set_enforce(root, True)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hook_text(root), foreign)
        self.assertIn(support.localized('existing hook belongs to the project', "чужой хук"), out)

    def test_unmarked_lipi_hook_is_foreign(self):
        """Хук с вызовом lipi без метки принадлежит проекту."""
        root = self.project()
        foreign = "#!/bin/sh\nexec lipi check --staged\n"
        support.w(self.hook(root), foreign)
        for enforce in (False, True):
            with self.subTest(enforce=enforce):
                self.set_enforce(root, enforce)
                before = self.hook(root).stat().st_mtime_ns
                code, out = support.init(root)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.hook_text(root), foreign)
                self.assertEqual(self.hook(root).stat().st_mtime_ns, before)

    def test_enforce_flag_for_new_project(self):
        root = self.tmp / "root"
        root.mkdir()
        support.git_init(root)
        code, out = support.init(root, "--enforce")
        self.assertEqual(code, 0, out)
        self.assert_lipi_hook(root)
        self.assertIn(STRICT, self.rules(root))
        cfg = json.loads((root / "lipi.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["enforce"], True)

    def test_hook_argument_is_unknown(self):
        """Ключа --hook у init нет: argparse-отказ, в справке его нет."""
        root = self.tmp / "root"
        root.mkdir()
        code, out = support.init(root, "--hook")
        self.assertNotEqual(code, 0)
        self.assertEqual(code, 2, out)
        self.assertIn(support.localized("unrecognized arguments", "неизвестные аргументы"), out)
        code, out = support.run(support.PY + [str(support.INIT), "--help"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("--hook", out)


class ReapplyTest(Base):
    """lipi init: хук и правила агента приводятся к enforce."""

    def test_installs_hook_when_enforce_true(self):
        """enforce: true и init — хук поставлен, версия та же."""
        root = self.project()
        self.assert_no_hook(root)
        self.set_enforce(root, True)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized('created:   %s (lipi)', "создан:    %s (lipi)") % HOOK_REL, out)
        self.assert_lipi_hook(root)
        self.assertIs(self.lock(root)["enforce"], True)

    def test_removes_own_hook_when_enforce_false(self):
        """После смены на false init убирает свой хук и сообщает."""
        root = self.project()
        self.set_enforce(root, True)
        self.assertEqual(support.init(root)[0], 0)
        self.assert_lipi_hook(root)
        self.set_enforce(root, False)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assert_no_hook(root)
        self.assertIn(support.localized('removed:   %s (lipi)', "удалён:    %s (lipi)") % HOOK_REL, out)
        self.assertIn(SOFT, self.rules(root))
        self.assertNotIn(STRICT, self.rules(root))
        self.assertIs(self.lock(root)["enforce"], False)
        # после init проверка чистая: V3 не ругается на расхождение
        code, out = self.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_foreign_hook_is_kept(self):
        """Чужой pre-commit init не трогает, даже при enforce: true."""
        root = self.project()
        foreign = "#!/bin/sh\nexec make lint\n"
        support.w(self.hook(root), foreign)
        self.set_enforce(root, True)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hook_text(root), foreign)
        self.assertIn(support.localized('existing hook belongs to the project', "чужой хук"), out)

    def test_rewrites_rules_when_enforce_changes(self):
        """Смена enforce: init перерисовывает правила агента."""
        root = self.project()
        self.assertIn(SOFT, self.rules(root))
        self.set_enforce(root, True)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assertIn(STRICT, self.rules(root))
        self.assertNotIn(SOFT, self.rules(root))
        # правило — файл lipi: отпечаток в lock сходится с файлом
        lock = self.lock(root)
        digest = hashlib.sha256(
            (root / support.LIPI_DIR / "README.md").read_bytes()).hexdigest()
        self.assertEqual(lock["files"][support.LIPI_DIR + "/README.md"], digest)

    def test_v3_reports_before_init(self):
        """До init V3 предупреждает, что правила отрисованы с другим enforce."""
        root = self.project()
        self.set_enforce(root, True)
        code, out = self.check(root)
        self.assertEqual(code, 0, out)
        self.assertTrue(support.found(out, "V3"), out)
        self.assertIn(support.localized('warning V3', "предупреждение V3"), out)
        self.assertIn("enforce", out)
        self.assertIn("lipi init", out)
        self.assertIn(SOFT, self.rules(root))
        # после init расхождение снято
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        code, out = self.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_dry_run_changes_nothing(self):
        """init --dry-run показывает хук и правила, но ничего не меняет."""
        root = self.project()
        self.set_enforce(root, True)
        before = self.rules(root)
        code, out = support.init(root, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn(support.localized("will create:   %s (lipi)",
                                        "будет создан:    %s (lipi)") % HOOK_REL, out)
        self.assert_no_hook(root)
        self.assertEqual(self.rules(root), before)
        self.assertIs(self.lock(root)["enforce"], False)


class RulesTest(Base):
    """Правила агента отрисовываются по enforce (ADR-011)."""

    def test_soft_by_default(self):
        """Без ключа: запустить check, ошибки своей правки — исправить или сообщить."""
        root = self.project()
        rules = self.rules(root)
        self.assertIn(SOFT, rules)
        self.assertNotIn(STRICT, rules)

    def test_strict_when_enforce_true(self):
        """При enforce: true ошибки своей правки исправляются до коммита."""
        root = self.project(enforce=True)
        rules = self.rules(root)
        self.assertIn(STRICT, rules)
        self.assertNotIn(SOFT, rules)

    def test_render_uses_enforce(self):
        """render ставит текст по enforce, плейсхолдеров в файлах нет."""
        init = init_module()
        root = self.tmp / "render"
        root.mkdir()
        for enforce in (False, True):
            files, _ = init.render(root, "package", "docs", "workflow",
                                   enforce=enforce)
            rendered = {init.rel_name(root, p): text for p, text in files.items()}
            rules = rendered[support.LIPI_DIR + "/README.md"]
            self.assertNotIn("{{ENFORCE}}", rules)
            self.assertIn(STRICT if enforce else SOFT, rules)


class CheckIndependenceTest(Base):
    """Код возврата lipi check от enforce не зависит (ADR-011)."""

    def test_return_code_same_with_and_without_enforce(self):
        """Одна и та же ошибка даёт код 1 при обоих значениях ключа."""
        root = self.project()
        support.w(root / "docs" / "README.md", "# X\n\n[битая](net.md)\n")
        code_false, out_false = self.check(root)
        self.assertEqual(code_false, 1, out_false)
        self.assertTrue(support.found(out_false, "D1"), out_false)
        self.set_enforce(root, True)
        self.assertEqual(support.init(root)[0], 0)
        code_true, out_true = self.check(root)
        self.assertEqual(code_true, code_false, out_true)
        self.assertTrue(support.found(out_true, "D1"), out_true)
        self.assertIn(support.localized('errors: 1, warnings: 0', "ошибок: 1, предупреждений: 0"), out_true)

    def test_clean_project_code_zero_both(self):
        """Чистый проект: код 0 при false и при true."""
        root = self.project()
        self.assertEqual(self.check(root)[0], 0)
        self.set_enforce(root, True)
        self.assertEqual(support.init(root)[0], 0)
        self.assertEqual(self.check(root)[0], 0)

    def test_code_does_not_depend_on_enforce_without_reapply(self):
        """Даже без init смена enforce не меняет код возврата: V3 — предупреждение."""
        root = self.project()
        code_false, out_false = self.check(root)
        self.set_enforce(root, True)
        code_true, out_true = self.check(root)
        self.assertEqual(code_true, code_false, out_true)
        self.assertEqual(code_true, 0, out_true)
        self.assertTrue(support.found(out_true, "V3"), out_true)

    def test_enforce_must_be_bool(self):
        """C1: enforce не логическое значение — код 2 и сообщение."""
        root = self.project()
        for value in ("да", 1, None, []):
            self.set_enforce(root, value)
            code, out = self.check(root)
            self.assertEqual(code, 2, (value, out))
            self.assertTrue(support.found(out, "C1"), out)
            self.assertIn(support.localized('key "enforce": expected a boolean', "ключ «enforce»: ожидается логическое значение"), out)


if __name__ == "__main__":
    unittest.main()
