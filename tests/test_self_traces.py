"""test_self_traces.py — метки @trace в самом lipi (З18): пять сценариев на копиях. — lipi: ignore-trace

Копия lipi (без .git и набора тестов) разворачивается как проект с двумя
редакциями описания. Метки чекера в `src/lipi/checker/` указывают на таблицу
`docs/ru/codes.md`. На копии ставятся git-коммиты по датам и проверяется:

а) изменён только код под меткой — T2 (`--staged`) и A4 (`--audit`) срабатывают,
   в находке отмечен раздел `docs/ru/codes.md` и его якорь (D2);
б) изменены и код, и раздел `docs/ru/codes.md` — T2 молчит сразу, A4 молчит после коммита
   обоих файлов одним коммитом (у кода и раздела одна метка времени, и
   `git blame` не считает код новее);
в) открытая работа ссылается на раздел: изменённый код даёт запись `stale` с
   этой работой и статусом «в работе», без изменённого кода цепочки нет;
г) работа по разделу закрыта: цепочка показывает статус «завершён» (это не
   открытая работа), а при обновлённом разделе `stale` не срабатывает;
д) изменённый файл закоммичен: без `--staged`/`--diff` T2 молчит, `--diff`
   даёт и T2, и запись `stale`.

У каждого кода проверки есть строка-якорь в обеих редакциях таблицы кодов
и метка в модулях `checker/` (`RE_TRACE`-метки разбираются так же, как чекером).

Запуск: python3 -m unittest tests.test_self_traces -v
"""
import itertools
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

TAG = support.TAG            # «@trace» по частям: чекер lipi не примет за метку
CHECK_REL = "src/lipi/check.py"
CHECKER_REL = "src/lipi/checker"
CODES_REL = "docs/ru/codes.md"
# дата базового коммита копии: заведомо раньше «сейчас» — A4 по blame её увидит
DATE = "2026-01-01T10:00:00"
# Коды проверок, которым нужны и строка в таблице docs/ru/codes.md, и метка в чекере.
CODES = (["C1"] + ["D%d" % i for i in range(1, 8)] + ["L1", "L2", "L3"]
         + ["W%d" % i for i in range(1, 12)]
         + ["T1", "T2", "T3", "T4", "V1", "V2", "V3"] + ["A%d" % i for i in range(1, 9)]
         + ["P1"])
ANCHORS = [code.lower() for code in CODES]
# RE_TRACE чекера: коды одной метки — через запятую, без пробела после неё.
RE_LABEL = re.compile(r"%s\s+(\S+(?:\s*,\s*\S+)*)" % re.escape(TAG))
RE_ROW = re.compile(r'^\| <a id="([a-z0-9-]+)"></a>([A-Z][0-9]+) \|', re.M)


def run_check(root, *args):
    """Чекер копии: это и есть её проект, поэтому запускается src/lipi/check.py."""
    return support.run(support.PY + [str(root / CHECK_REL)] + list(args), cwd=str(root))


def check_json(root, *args):
    """Как support.check_json, но чекером копии: (код возврата, объект JSON)."""
    if "--format" not in args:
        args = ("--format", "json") + args
    code, out = run_check(root, *args)
    try:
        return code, json.loads(out)
    except ValueError:
        raise AssertionError("чекер вернул не JSON:\n" + out)


def labels_line(root, anchor):
    """Путь и номер строки метки docs/ru/codes.md#anchor в модулях чекера копии."""
    pattern = re.compile(r"%s\s+\S*%s#%s(?![A-Za-z0-9-])"
                         % (re.escape(TAG), re.escape(CODES_REL), re.escape(anchor)))
    for path in sorted((root / CHECKER_REL).glob("*.py")):
        lines = path.read_text(encoding="utf-8").split("\n")
        for n, s in enumerate(lines, 1):
            if pattern.search(s):
                return path.relative_to(root).as_posix(), n
    raise AssertionError("в %s нет метки %s docs/ru/codes.md#%s" % (CHECKER_REL, TAG, anchor))


def change_code_under(root, anchor):
    """Правка кода под меткой: строка-комментарий сразу после метки.

    Поведение чекера не меняется, но строка попадает в область метки: её видят
    T2 (по --staged) и A4 (по git blame).
    """
    rel_path, line = labels_line(root, anchor)
    path = root / rel_path
    lines = path.read_text(encoding="utf-8").split("\n")
    lines.insert(line, "# правка кода под меткой (тест З18)")
    path.write_text("\n".join(lines), encoding="utf-8")
    return rel_path


def change_codes_section(root, anchor, note=" правка для теста"):
    """Правка раздела, на который указывает метка: строки таблицы кодов."""
    path = root / CODES_REL
    lines = path.read_text(encoding="utf-8").split("\n")
    marker = '<a id="%s"></a>' % anchor
    for i, s in enumerate(lines):
        if marker in s:
            row = s.rstrip()
            assert row.endswith("|"), row
            lines[i] = row[:-1].rstrip() + note + " |"
            path.write_text("\n".join(lines), encoding="utf-8")
            return
    raise AssertionError("в %s нет строки с якорем %s" % (CODES_REL, anchor))


def link_work_at_section(root, rel_plan, anchor="d2"):
    """Добавляет в рабочий документ ссылку на раздел `docs/ru/codes.md` — связь для stale."""
    path = root / rel_plan
    text = path.read_text(encoding="utf-8")
    path.write_text(text.rstrip("\n") + f"\n\nСм. [коды](../../../{CODES_REL}#{anchor}).\n",
                    encoding="utf-8")


def stale_for(data, anchor):
    """Записи цепочки устаревания для якоря data['structure']['stale']."""
    return [s for s in data["structure"]["stale"] if s["anchor"] == anchor]


class SelfTraceCase(unittest.TestCase):
    """Копия lipi как проект. Базовая копия одна, каждый тест получает свою."""

    _counter = itertools.count()

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lipi-self-"))
        cls.base = cls.tmp / "base"
        support.lipi_copy(cls.base)          # без .git и набора тестов: каталог — проект

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self, name="case"):
        """Независимая копия репозитория lipi без .git."""
        root = self.tmp / ("%s-%d" % (name, next(self._counter)))
        self.addCleanup(shutil.rmtree, str(root), True)
        shutil.copytree(str(self.base), str(root))
        return root

    def repository(self, name="repo"):
        """Копия с одним коммитом «init» датой DATE — база для A4 и --staged."""
        root = self.project(name)
        support.git_init(root)
        code, out = support.commit(root, "init", DATE)
        self.assertEqual(code, 0, out)
        return root


class SelfCheckCase(SelfTraceCase):
    """Копия lipi — проект, который чекер проверяет сам себя."""

    def test_copy_is_clean(self):
        """Свои метки и якоря разрешаются: T1 и A4 на копии молчат."""
        root = self.repository()
        code, data = check_json(root)
        self.assertEqual(code, 0, data)
        self.assertEqual(data["errors"], [])
        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0, data)
        self.assertEqual([w for w in data["warnings"] if w["code"] == "A4"], [],
                         "код и раздел в одном коммите: расхождения быть не может")


class CodeOnlyChange(SelfTraceCase):
    """Сценарий а: изменён только код под меткой."""

    def test_t2_and_a4_ring(self):
        """T2 (--staged) и A4 (--audit) находят расхождение, раздел отмечен."""
        root = self.repository()
        changed_file = change_code_under(root, "d2")
        support.git(root, "add", changed_file)

        code, data = check_json(root, "--staged")
        self.assertEqual(code, 0, data)
        t2 = [w for w in data["warnings"] if w["code"] == "T2"]
        self.assertTrue(any(w["subject"] == f"{CODES_REL}#d2" and w["file"] == changed_file
                            for w in t2), data["warnings"])

        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0, data)
        a4 = [w for w in data["warnings"] if w["code"] == "A4"]
        self.assertTrue(any(w["file"] == CODES_REL and w["line"] > 0
                            and f"{CODES_REL}#d2" in w["message"] for w in a4),
                        data["warnings"])


class CodeAndSectionChange(SelfTraceCase):
    """Сценарий б: изменены и код, и раздел `docs/ru/codes.md`."""

    def test_t2_and_a4_silent(self):
        """T2 молчит сразу; A4 — после коммита обоих файлов одним коммитом."""
        root = self.repository()
        change_code_under(root, "d2")
        change_codes_section(root, "d2")
        support.git(root, "add", "-A")

        code, data = check_json(root, "--staged")
        self.assertEqual(code, 0, data)
        self.assertEqual([w for w in data["warnings"] if w["code"] == "T2"], [],
                         "код и раздел изменены вместе")

        code, out = support.commit(root, "код и раздел", "2026-01-02T10:00:00")
        self.assertEqual(code, 0, out)
        code, data = check_json(root, "--audit")
        self.assertEqual(code, 0, data)
        self.assertEqual([w for w in data["warnings"] if w["code"] == "A4"], [],
                         "код и раздел в одном коммите: код не новее раздела")


class OpenWorkStale(SelfTraceCase):
    """Сценарий в: открытая работа ссылается на раздел."""

    PLAN = "workflow/plan/2026/pln-900-open-test.md"

    def open_plan(self, root):
        """Создаёт план со статусом «в работе» в копии."""
        support.w(root / self.PLAN,
                  "# Открытая работа для теста\n\n"
                  "- Created: 2026-01-01\n"
                  "- Updated: 2026-01-01\n"
                  "- Status: in progress\n\n"
                  "## Purpose\n\nДля сценария в.\n\n"
                  "## Completion criteria\n\nТест проходит.\n")
        code, out = run_check(root, "--write-index")
        assert code == 0, out

    def test_open_work_in_chain(self):
        """Изменён код, раздел нет: stale несёт работу и её статус «в работе»."""
        root = self.repository()
        self.open_plan(root)
        link_work_at_section(root, self.PLAN)
        changed_file = change_code_under(root, "d2")
        support.git(root, "add", changed_file)

        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0, data)
        stale = stale_for(data, f"{CODES_REL}#d2")
        self.assertTrue(stale, data["structure"]["stale"])
        self.assertEqual(stale[0]["page"], CODES_REL)
        self.assertEqual(stale[0]["file"], changed_file)
        self.assertEqual(stale[0]["covers"], [],
                         "в lipi нет отдельного описания системы — справки нет")
        self.assertIn({"id": "PLN-900", "status": "in progress"}, stale[0]["works"])

    def test_open_work_alone_no_chain(self):
        """Код не изменён: одна открытая ссылка работы цепочку не строит."""
        root = self.repository()
        self.open_plan(root)
        link_work_at_section(root, self.PLAN)

        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["structure"]["stale"], [])
        self.assertEqual([w for w in data["warnings"] if w["code"] == "T2"], [])


class ClosedWorkStale(SelfTraceCase):
    """Сценарий г: работа по разделу закрыта (статус «завершён», итог есть)."""

    PLAN = "workflow/plan/2026/pln-901-closed-test.md"

    def closed_plan(self, root):
        """Создаёт завершённый план со ссылкой на раздел кодов."""
        support.w(root / self.PLAN,
                  "# Завершённый план для теста\n\n"
                  "- Created: 2026-01-01\n"
                  "- Updated: 2026-01-02\n"
                  "- Status: completed\n"
                  "- Result: критерий выполнен.\n"
                  "- Closed: 2026-01-02\n\n"
                  "## Purpose\n\nДля сценария г.\n\n"
                  "## Completion criteria\n\nТест проходит.\n")
        link_work_at_section(root, self.PLAN)
        code, out = run_check(root, "--write-index")
        self.assertEqual(code, 0, out)

    def test_closed_work_status_in_chain(self):
        """Цепочка показывает закрытую работу закрытой, а не открытой."""
        root = self.repository()
        self.closed_plan(root)
        changed_file = change_code_under(root, "d2")
        support.git(root, "add", changed_file)

        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0, data)
        stale = stale_for(data, f"{CODES_REL}#d2")
        self.assertTrue(stale, data["structure"]["stale"])
        self.assertIn({"id": "PLN-901", "status": "completed"}, stale[0]["works"])
        self.assertNotIn({"id": "PLN-901", "status": "in progress"}, stale[0]["works"],
                         "закрытая работа не выдаёт себя за открытую")

    def test_closed_work_silent_when_section_updated(self):
        """Код и раздел изменены вместе: stale не срабатывает и у закрытой работы."""
        root = self.repository()
        self.closed_plan(root)
        change_code_under(root, "d2")
        change_codes_section(root, "d2")
        support.git(root, "add", "-A")

        code, data = check_json(root, "--staged", "--structure")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["structure"]["stale"], [])
        self.assertEqual([w for w in data["warnings"] if w["code"] == "T2"], [])


class CommittedChange(SelfTraceCase):
    """Сценарий д: файл изменён и закоммичен, незакоммиченных правок нет."""

    def test_t2_needs_selected_diff(self):
        """Без --staged/--diff T2 молчит; --diff находит и T2, и stale."""
        root = self.repository()
        change_code_under(root, "d2")
        code, out = support.commit(root, "код под меткой", "2026-01-02T10:00:00")
        self.assertEqual(code, 0, out)

        code, data = check_json(root)
        self.assertEqual(code, 0, data)
        self.assertEqual([w for w in data["warnings"] if w["code"] == "T2"], [])
        code, data = check_json(root, "--staged")
        self.assertEqual(code, 0, data)
        self.assertEqual([w for w in data["warnings"] if w["code"] == "T2"], [],
                         "всё закоммичено: в --staged изменений нет")

        code, data = check_json(root, "--diff", "HEAD~1...HEAD")
        self.assertEqual(code, 0, data)
        t2 = [w for w in data["warnings"] if w["code"] == "T2"]
        self.assertTrue(any(w["subject"] == f"{CODES_REL}#d2" for w in t2), data["warnings"])

        code, data = check_json(root, "--diff", "HEAD~1...HEAD", "--structure")
        self.assertEqual(code, 0, data)
        self.assertTrue(stale_for(data, f"{CODES_REL}#d2"), data["structure"]["stale"])


class LabelsCoverCodes(unittest.TestCase):
    """У каждого кода проверки есть якорь в обеих редакциях и метка в чекере."""

    def codes(self, language):
        return (support.LIPI / "docs" / language / "codes.md").read_text(encoding="utf-8")

    def test_codes_rows_have_anchors(self):
        """Каждый код — отдельная строка таблицы со своим якорем (строчные)."""
        for language in ("en", "ru"):
            with self.subTest(language=language):
                rows = {code: anchor for anchor, code in RE_ROW.findall(self.codes(language))}
                self.assertEqual(sorted(rows), sorted(CODES))
                for code, anchor in rows.items():
                    self.assertEqual(anchor, code.lower(), "якорь строки %s" % code)

    def test_every_code_has_label(self):
        """RE_TRACE-метки модулей checker покрывают все коды и их якоря."""
        text = "\n".join(path.read_text(encoding="utf-8")
                         for path in sorted((support.LIPI / CHECKER_REL).glob("*.py")))
        labelled = []
        for m in RE_LABEL.finditer(text):
            for token in m.group(1).split(","):
                token = token.strip()
                self.assertTrue(token, "пустой код в метке: коды — через запятую "
                                       "без пробела, иначе RE_TRACE видит пустой код")
                # Общие помощники чекера также размечены настройками проекта;
                # здесь проверяется полнота меток именно на таблицу кодов.
                if not token.startswith(f"{CODES_REL}#"):
                    continue
                labelled.append(token.split("#", 1)[1])
        self.assertEqual(sorted(set(labelled)), sorted(ANCHORS),
                         "набор меток разошёлся с кодами проверок")
        anchors = set(re.findall(r'<a id="([^"]+)"', self.codes("ru")))
        self.assertEqual(sorted(set(ANCHORS) - anchors), [],
                         "у кода нет явного якоря в docs/ru/codes.md — T1 не разрешит метку")


if __name__ == "__main__":
    unittest.main()
