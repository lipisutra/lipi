"""test_speed.py — бюджет скорости быстрых проверок.

Синтетический проект во временном каталоге: 300 страниц описания в docs/,
связанных указателем docs/README.md, и 5000 небольших файлов кода в src/ без
меток — scan_code читает каждый файл, но находок нет. `check` без
--audit/--structure/--staged замеряется вокруг support.check(): тест падает,
при LIPI_TEST_TIMING=1, если быстрые проверки дольше 2 с — это бюджет CI (цель на машине
разработки — 1 с).

Обе стороны бюджета: маленький проект (только что развёрнутый) заведомо
быстрее, большой — укладывается. Проекты генерируются один раз на класс
(setUpClass), поэтому весь модуль стоит около секунды, а не по секунде на
каждый тест.

Запуск: python3 -m unittest tests.test_speed
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

# Синтетический проект: сколько страниц описания и файлов кода генерировать.
PAGES = 300
CODE_FILES = 5000

def add_pages(root):
    """300 страниц docs/ и строки указателя в docs/README.md."""
    rows = []
    for i in range(PAGES):
        name, anchor = "page-%03d" % i, "anchor-%03d" % i
        support.w(root / "docs" / (name + ".md"),
                  "# Страница %03d\n\n## Раздел %03d <a id=\"%s\"></a>\n\nТекст.\n"
                  % (i, i, anchor))
        rows.append("| %03d | [%03d](%s.md#%s) |" % (i, i, name, anchor))
    support.sub(root / "docs" / "README.md", "| --- | --- |",
                "| --- | --- |\n" + "\n".join(rows))


def add_code(root):
    """5000 небольших файлов src/ без меток: scan_code занят, находок нет."""
    src = root / "src"
    src.mkdir(exist_ok=True)
    for i in range(CODE_FILES):
        (src / ("module_%04d.py" % i)).write_text(
            "def function_%d(value):\n    return value + %d\n" % (i, i),
            encoding="utf-8")


class SpeedBudgetCase(unittest.TestCase):
    """Бюджет быстрых проверок на маленьком и синтетически большом проекте."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lipi-test-speed-"))
        # маленький проект — обычный каркас, только что развёрнутый
        cls.small = cls.tmp / "small"
        cls.small.mkdir()
        code, out = support.init(cls.small)
        if code != 0:
            raise AssertionError("init маленького проекта не прошёл: %s" % out)
        # большой проект — тот же каркас плюс 300 страниц и 5000 файлов кода
        cls.big = cls.tmp / "big"
        cls.big.mkdir()
        code, out = support.init(cls.big)
        if code != 0:
            raise AssertionError("init большого проекта не прошёл: %s" % out)
        add_pages(cls.big)
        add_code(cls.big)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_small_project_is_cheap(self):
        with support.time_budget(self, "check: empty project"):
            code, out = support.check(self.small)
        self.assertEqual(code, 0, out)

    def test_big_project_fits_budget(self):
        with support.time_budget(self, "check: 300 pages and 5000 code files"):
            code, out = support.check(self.big)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
