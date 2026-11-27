"""test_ci.py — задание CI в проекте (ADR-010, ADR-011).

Одна вещь с трёх сторон:

- шаблон `src/lipi/locale/en/templates/lipi/common/ci/github.yml` — push и pull
  request, checkout с полной историей, setup-python, установка lipi через
  pipx из тега первой цифры версии (ADR-010), проверка установленной
  командой `lipi check --format github`; строгость берётся из ключа
  `enforce` (ADR-011): при false шаг не краснеет через
  `continue-on-error: true`, при true краснеет;
- `render` кладёт шаблон в `.github/workflows/lipi.yml`, а не в
  `.agents/lipi/`, и это файл lipi: его отпечаток пишется в lock-файл;
- `lipi init --ci github` и `lipi ci github` создают файл и отпечаток, V3
  ловит ручную правку, а `lipi init` заменяет изменённый файл.

Шаблон проверяется текстом из `templates/` и отрисовкой `init.render`:
подстановки `{{MAJOR}}` (первая цифра версии) и `{{ENFORCE}}`
(строгость ADR-011) живут в `init.py`. У каждого поведения две стороны:
файл создан / не создан, V3 молчит / срабатывает, init заменяет /
не создаёт лишнего.

Запуск: python3 -m unittest tests.test_ci
"""
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support
from tests.support import localized

# шаблон, который render переносит в .github/workflows/lipi.yml
CI_TEMPLATE = support.SRC / "locale" / "en" / "templates" / "lipi" / "common" / "ci" / "github.yml"
# подстановки шаблона: первая цифра версии и строгость проекта ADR-011
MAJOR_TOKEN = "{{MAJOR}}"
ENFORCE_TOKEN = "{{ENFORCE}}"
# форма команд CI: установка первой цифрой версии и проверка установленной
# командой (ADR-010), без копии чекера в проекте
INSTALL_COMMAND = "pipx install git+https://github.com/lipisutra/lipi@v"
PR_COMMAND = "lipi check --diff origin/${{ github.base_ref }}...HEAD --format github"
PUSH_COMMAND = "lipi check --format github"
OLD_COMMAND = "python .agents/lipi/check.py"
# строка, которую подставляет {{ENFORCE}} при "enforce": false
CONTINUE_ON_ERROR = "        continue-on-error: true"
VERSION = support.VERSION
MAJOR = VERSION.split(".")[0]
STEP_RE = re.compile(r"(?m)^      - ")


def init_module():
    """Модуль lipi.init в процессе теста (для render)."""
    src = str(support.SRC.parent)
    if src not in sys.path:
        sys.path.insert(0, src)
    from lipi import init as module
    return module


def ci_path(root):
    """Путь задания CI в проекте."""
    return Path(root) / support.CI_REL


def read_lock(root):
    return json.loads((Path(root) / support.LOCK_REL).read_text(encoding="utf-8"))


def sha256_path(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def render_ci(enforce=False):
    """Отрисованный шаблон CI для "enforce": false/true.

    `init.render` подставляет `{{MAJOR}}` — первая цифра версии в теге
    установки — и `{{ENFORCE}}` — целая строка шага: при false
    `        continue-on-error: true`, при true пусто (строки нет).
    """
    init = init_module()
    tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-render-"))
    root = (tmp / "root").resolve()
    root.mkdir()
    files, _ = init.render(root, "project", "docs", "workflow", enforce=enforce)
    return files[ci_path(root)]


def steps(text):
    """Блоки шагов workflow: каждый от «      - » до следующего."""
    return STEP_RE.split(text)[1:]


def step_with(text, command):
    """Единственный шаг workflow, запускающий command."""
    found = [block for block in steps(text) if command in block]
    assert len(found) == 1, "%r: шагов %d" % (command, len(found))
    return found[0]


def code_lines(text):
    """Строки workflow без комментариев: поведение, а не пояснение в шапке."""
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


class TemplateTest(unittest.TestCase):
    """Шаблон CI и место, куда его кладёт render."""

    def test_triggers_and_setup(self):
        """Шаблон: push и pull request, checkout с полной историей, setup-python."""
        text = CI_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("on:\n  push:\n  pull_request:\n", text)
        self.assertIn("actions/checkout@v4", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("actions/setup-python@v5", text)

    def test_installs_lipi_of_same_major(self):
        """Ставится последняя версия той же первой цифры: тег v<MAJOR> (ADR-010)."""
        text = CI_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(INSTALL_COMMAND + MAJOR_TOKEN, text)
        rendered = render_ci()
        self.assertIn(INSTALL_COMMAND + MAJOR, rendered)
        self.assertNotIn(MAJOR_TOKEN, rendered)

    def test_commands_by_installed_lipi(self):
        """Проверяет установленная команда: PR — с --diff по базе, push — без."""
        for enforce in (False, True):
            with self.subTest(enforce=enforce):
                rendered = render_ci(enforce)
                # копии чекера в проекте нет (ADR-010)
                self.assertNotIn(OLD_COMMAND, rendered)
                self.assertNotIn(".agents/lipi/check.py", rendered)
                pr = step_with(rendered, PR_COMMAND)
                self.assertIn("if: github.event_name == 'pull_request'", pr)
                push = step_with(rendered, PUSH_COMMAND)
                self.assertIn("if: github.event_name == 'push'", push)

    def test_enforce_placeholder_in_both_check_steps(self):
        """{{ENFORCE}} стоит у обоих шагов проверки: строгость одна на проект."""
        text = CI_TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(text.count(ENFORCE_TOKEN), 2)

    def test_enforce_false_only_annotates(self):
        """"enforce": false — оба шага проверки с continue-on-error: true."""
        rendered = render_ci(False)
        self.assertNotIn(ENFORCE_TOKEN, rendered)
        self.assertEqual(code_lines(rendered).count("continue-on-error: true"), 2)
        for command in (PR_COMMAND, PUSH_COMMAND):
            self.assertIn(CONTINUE_ON_ERROR + "\n", step_with(rendered, command))

    def test_enforce_true_fails_run(self):
        """"enforce": true — continue-on-error нет, ошибки краснят прогон."""
        rendered = render_ci(True)
        self.assertNotIn(ENFORCE_TOKEN, rendered)
        self.assertNotIn("continue-on-error", code_lines(rendered))
        self.assertIn(PR_COMMAND, rendered)
        self.assertIn(PUSH_COMMAND, rendered)

    def test_render_puts_it_into_github_workflows(self):
        """render кладёт шаблон в .github/workflows/lipi.yml, а не в .agents/lipi/."""
        tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-render-"))
        try:
            root = (tmp / "root").resolve()
            root.mkdir()
            init = init_module()
            files, _ = init.render(root, "package", "docs", "workflow")
            rendered = {init.rel_name(root, p): p for p in files}
            self.assertIn(support.CI_REL, rendered)
            self.assertEqual(rendered[support.CI_REL],
                             root / ".github" / "workflows" / "lipi.yml")
            # в .agents/lipi/ шаблон CI не попадает
            self.assertFalse([name for name in rendered
                              if name.startswith(".agents/lipi/ci/")], rendered)
            # команду проверки задаёт шаблон; старую копию чекера render не кладёт
            text = files[rendered[support.CI_REL]]
            self.assertIn(PUSH_COMMAND, text)
            self.assertNotIn(OLD_COMMAND, text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class InitCiTest(unittest.TestCase):
    """init --ci github: файл и отпечаток в lock-файле."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-init-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_file_and_lock_fingerprint(self):
        """init --ci github создаёт файл, отпечаток в lock и чистую проверку."""
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)
        path = ci_path(self.root)
        self.assertTrue(path.is_file())
        self.assertIn(support.CI_REL, out)
        lock = read_lock(self.root)
        self.assertEqual(lock["lipi"], VERSION)
        self.assertEqual(lock["files"][support.CI_REL], sha256_path(path))
        # это файл lipi: лежит не в .agents/lipi/, но в lock-файле
        self.assertFalse((self.root / ".agents" / "lipi" / "ci").exists())
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_without_flag_has_no_ci(self):
        """init без --ci github файла CI не создаёт и в lock не пишет."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertFalse(ci_path(self.root).exists())
        self.assertNotIn(support.CI_REL, read_lock(self.root)["files"])
        self.assertNotIn(support.CI_REL, out)

    def test_second_init_keeps_file_and_lock(self):
        """Повторный init --ci github файл не меняет и отпечаток не сдвигает."""
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)
        before = ci_path(self.root).read_bytes(), read_lock(self.root)
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)
        self.assertEqual((ci_path(self.root).read_bytes(), read_lock(self.root)), before)


class CiCommandTest(unittest.TestCase):
    """lipi ci github: задание CI в развёрнутом проекте."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-cmd-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_adds_file_and_fingerprint(self):
        """lipi ci github создаёт файл и записывает отпечаток в lock."""
        code, out = support.cli(self.root, "ci", "github")
        self.assertEqual(code, 0, out)
        path = ci_path(self.root)
        self.assertTrue(path.is_file())
        self.assertIn(support.CI_REL, out)
        self.assertEqual(read_lock(self.root)["files"][support.CI_REL],
                         sha256_path(path))
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_updates_modified_file(self):
        """Правку проекта lipi ci github заменяет шаблоном и обновляет отпечаток."""
        code, out = support.cli(self.root, "ci", "github")
        self.assertEqual(code, 0, out)
        support.w(ci_path(self.root), "# правка проекта\n")
        code, out = support.cli(self.root, "ci", "github")
        self.assertEqual(code, 0, out)
        self.assertIn(support.CI_REL, out)
        self.assertNotIn("правка проекта", ci_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(read_lock(self.root)["files"][support.CI_REL],
                         sha256_path(ci_path(self.root)))
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)

    def test_path_argument(self):
        """lipi ci github <папка> работает с указанным проектом."""
        code, out = support.cli(self.tmp, "ci", "github", str(self.root))
        self.assertEqual(code, 0, out)
        self.assertTrue(ci_path(self.root).is_file())

    def test_requires_deployed_project(self):
        """lipi ci github без lipi.json — код 2 и подсказка про init."""
        empty = self.tmp / "empty"
        empty.mkdir()
        code, out = support.cli(empty, "ci", "github")
        self.assertEqual(code, 2, out)
        self.assertIn("lipi init", out)

    def test_unknown_platform(self):
        """Кроме github заданий CI пока нет: код 2."""
        code, out = support.cli(self.root, "ci", "gitlab")
        self.assertEqual(code, 2, out)
        self.assertIn(localized('only github', "только github"), out)
        code, out = support.cli(self.root, "ci")
        self.assertEqual(code, 2, out)


class V3Test(unittest.TestCase):
    """V3: задание CI — файл lipi, ручная правка не проходит проверку."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-v3-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_modified_file_is_error(self):
        """Изменённый вручную .github/workflows/lipi.yml — ошибка V3."""
        path = ci_path(self.root)
        support.w(path, path.read_text(encoding="utf-8") + "\n# правка\n")
        code, out = support.check(self.root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)
        self.assertIn(support.CI_REL, out)


class ReapplyCiTest(unittest.TestCase):
    """lipi init заменяет подключённый файл CI, но не создаёт необязательный."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-ci-reapply-")).resolve()
        self.root = self.tmp / "root"
        self.root.mkdir()
        code, out = support.init(self.root, "--ci", "github")
        self.assertEqual(code, 0, out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_replaces_modified_file(self):
        """Изменённый CI-файл заменяется шаблоном, lock и проверка сходятся."""
        path = ci_path(self.root)
        support.w(path, path.read_text(encoding="utf-8") + "\n# правка проекта\n")
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.CI_REL, out)
        self.assertNotIn("правка проекта", path.read_text(encoding="utf-8"))
        self.assertEqual(read_lock(self.root)["files"][support.CI_REL],
                         sha256_path(path))
        code, out = support.check(self.root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_deleted_file_is_created_again(self):
        """Удалённый CI-файл init создаёт заново: он подключён."""
        ci_path(self.root).unlink()
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn(support.CI_REL, out)
        self.assertTrue(ci_path(self.root).is_file())

    def test_not_created_in_project_without_ci(self):
        """Проект без подключённого CI init файл не создаёт."""
        root = self.tmp / "plain"
        root.mkdir()
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        code, out = support.init(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(ci_path(root).exists())
        self.assertNotIn(support.CI_REL, read_lock(root)["files"])


if __name__ == "__main__":
    unittest.main()
