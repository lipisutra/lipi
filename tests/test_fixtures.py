"""test_fixtures.py — ключевые проверки чекера на двух вымышленных проектах.

tests/fixtures/package/ — пакет: описание, код с метками, все типы рабочих
документов. tests/fixtures/app/ — приложение: справка, описание системы,
covers. Каждый тест работает на временной копии проекта.

1. Чисто: чекер и аудит не находят ничего — нет ложных срабатываний.
2. Эталон графа: --structure совпадает с fixtures/<проект>.structure.json.
   Пересоздать после намеренного изменения: LIPI_GOLDEN=1.
3. Одна поломка — один код: правка в копии и ожидаемый код находки.

Запуск: python3 -m unittest tests.test_fixtures
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import run

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
CHECK = HERE.parent / "src" / "lipi" / "check.py"
TAG = "@" + "trace"          # по частям, чтобы чекер lipi не принял за метку
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def check(root, *args, env=None):
    """(код возврата, объект JSON) чекера lipi по проекту root.

    env — окружение для чекера (например, CI="1", чтобы локальная
    пересборка указателя не гасила W7, З9).
    """
    code, out = run([sys.executable, "-B", str(CHECK), "--root", str(root),
                     "--format", "json"] + list(args), root, env=env)
    try:
        return code, json.loads(out)
    except ValueError:
        raise AssertionError("чекер вернул не JSON:\n" + out)


def codes(result, kind="errors"):
    return sorted(set(item["code"] for item in result.get(kind, [])))


def git(root, *args, date=None):
    env = dict(GIT_ENV)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    code, out = run(["git"] + list(args), root, env)
    assert code == 0, out


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, "%s: нет «%s»" % (path, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def normalize(structure):
    """Граф без зависимости от порядка обхода файлов."""
    def key(item):
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    out = dict(structure)
    for field in ("nodes", "edges", "stale"):
        if isinstance(out.get(field), list):
            out[field] = sorted(out[field], key=key)
    return out


HEADER = "- Created: 2026-11-01\n- Updated: 2026-11-01\n"

# (название, проект, правка копии, ожидаемый код ошибки)
BREAKS = [
    ("битый якорь в ссылке", "package",
     lambda r: replace(r / "docs/guide.md", "reference.md#max-discount", "reference.md#nope"), "D1"),
    ("повтор якоря на странице", "package",
     lambda r: replace(r / "docs/reference.md", '<a id="promo">', '<a id="max-discount">'), "D2"),
    ("страница-сирота", "package",
     lambda r: write(r / "docs/orphan.md", "# Сирота\n"), "D4"),
    ("описание ссылается на рабочие материалы", "package",
     lambda r: replace(r / "docs/guide.md", "Товары кладутся в корзину.",
                       "[План](../workflow/plan/2026/pln-002-promokody.md)"), "D5"),
    ("covers на несуществующий раздел", "app",
     lambda r: replace(r / "docs/discount.md", "covers: docs/development/rules.md#max-discount",
                       "covers: docs/development/rules.md#no-such"), "D6"),
    ("имя документа не по формату", "package",
     lambda r: write(r / "workflow/plan/2026/staryy-plan.md", "# Старый план\n"), "W1"),
    ("повтор номера", "package",
     lambda r: write(r / "workflow/plan/2026/pln-001-dubl.md",
                     "# Дубль\n\n" + HEADER + "- Status: new\n"), "W2"),
    ("статус не из списка", "package",
     lambda r: replace(r / "workflow/plan/2026/pln-002-promokody.md",
                       "Status: in progress", "Status: почти готов"), "W3"),
    ("завершён без итога", "package",
     lambda r: replace(r / "workflow/plan/2026/pln-002-promokody.md",
                       "Status: in progress", "Status: completed"), "W4"),
    ("мастер-план ссылается на завершённое", "package",
     lambda r: replace(r / "workflow/masterplan.md", "- PLN-002: промокоды.",
                       "- PLN-002: промокоды.\n- PLN-001: скидки."), "W5"),
    ("битая ссылка в рабочем документе", "package",
     lambda r: replace(r / "workflow/issue/2026/iss-001-chek-na-pochtu.md",
                       "письмо с чеком не приходит.", "письмо не приходит, см. [лог](net.md)."), "W6"),
    ("указатель устарел", "package",
     lambda r: replace(r / "workflow/issue/2026/iss-001-chek-na-pochtu.md",
                       "Status: open", "Status: in progress"), "W7",
     {"CI": "1"}),
    ("пустой обязательный раздел", "package",
     lambda r: replace(r / "workflow/issue/2026/iss-001-chek-na-pochtu.md",
                       "После оплаты письмо с чеком не приходит.\n", ""), "W8"),
    ("метка на несуществующий якорь", "package",
     lambda r: write(r / "src/extra.py", "# %s docs/reference.md#nope\n" % TAG), "T1"),
]


class Base(unittest.TestCase):
    def copy(self, name):
        tmp = Path(tempfile.mkdtemp(prefix="lipi-fixture-"))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        root = tmp / name
        shutil.copytree(str(FIXTURES / name), str(root))
        return root


class Clean(Base):
    def test_clean(self):
        for name in ("package", "app"):
            for mode in ([], ["--audit"]):
                with self.subTest(project=name, mode=mode or "quick"):
                    code, res = check(self.copy(name), *mode)
                    self.assertEqual((code, res["errors"], res["warnings"]), (0, [], []))


class Golden(Base):
    def test_structure(self):
        for name in ("package", "app"):
            with self.subTest(project=name):
                code, res = check(self.copy(name), "--structure")
                got = normalize(res["structure"])
                golden = FIXTURES / ("%s.structure.json" % name)
                if os.environ.get("LIPI_GOLDEN"):
                    golden.write_text(json.dumps(got, ensure_ascii=False, indent=2, sort_keys=True)
                                      + "\n", encoding="utf-8")
                self.assertTrue(golden.is_file(), "нет эталона %s: запустите с LIPI_GOLDEN=1" % golden.name)
                self.assertEqual(got, json.loads(golden.read_text(encoding="utf-8")),
                                 "граф изменился; если намеренно — LIPI_GOLDEN=1 и проверьте diff")


class Breaks(Base):
    def test_one_break_one_code(self):
        for title, name, breaker, expected, *extra in BREAKS:
            with self.subTest(title):
                root = self.copy(name)
                breaker(root)
                env = extra[0] if extra else None
                code, res = check(root, env=env)
                self.assertEqual(code, 1)
                self.assertIn(expected, codes(res))

    def test_bad_config(self):
        root = self.copy("package")
        replace(root / "lipi.json", '"docs"', '"doc"')
        code, out = run([sys.executable, "-B", str(CHECK), "--root", str(root)], root)
        self.assertEqual(code, 2)
        self.assertIn("C1", out)


class Git(Base):
    def repo(self, name):
        root = self.copy(name)
        git(root, "init", "-q")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "init", date="2026-11-01T10:00:00")
        return root

    def test_code_changed_description_not(self):
        root = self.repo("package")
        replace(root / "src/order.py", "default=0", "default=1")
        git(root, "add", "-A")
        code, res = check(root, "--staged")
        self.assertEqual(code, 0)
        self.assertIn("T2", codes(res, "warnings"))

    def test_code_and_description_changed(self):
        root = self.repo("package")
        replace(root / "src/order.py", "default=0", "default=1")
        replace(root / "docs/reference.md", "Скидки не суммируются.", "Скидки не суммируются: берётся наибольшая.")
        git(root, "add", "-A")
        code, res = check(root, "--staged")
        self.assertNotIn("T2", codes(res, "warnings"))

    def test_help_not_updated(self):
        root = self.repo("app")
        replace(root / "docs/development/rules.md", "Скидки не суммируются.", "Скидки не суммируются: берётся наибольшая.")
        git(root, "add", "-A")
        code, res = check(root, "--staged")
        warned = [w["file"] for w in res["warnings"] if w["code"] == "T2"]
        self.assertIn("docs/discount.md", warned)

    def test_code_newer_than_description(self):
        root = self.repo("package")
        replace(root / "src/order.py", "default=0", "default=1")
        git(root, "commit", "-qam", "code", date="2026-11-10T10:00:00")
        code, res = check(root, "--audit")
        self.assertIn("A4", codes(res, "warnings"))


if __name__ == "__main__":
    unittest.main()
