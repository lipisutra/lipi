"""Находки, уровни проверок и форматы вывода."""

from lipi.i18n import tr
from lipi import __version__

# Уровни проверок по умолчанию (ADR-010): единственный источник уровня
# находки — код → "error" или "warning". Находки берут уровень из таблицы, а
# не задают его на месте. Дисциплина выпусков: внутри одной первой цифры
# новый код может быть только "warning", а повышение уровня с "warning" до
# "error" — только при смене первой цифры; это проверяет тест выпуска
# (tests/test_release.py против тега v<первая цифра>.0.0).
# Три исключения уровня задаёт правило, а не таблица, и call-site передаёт
# level явно: V1 (совместимость версий), V3 (расхождение enforce) и
# предупреждение D2 о повторном slug заголовка.
CODE_LEVELS = {
    "C1": "error",
    "D1": "error", "D2": "error", "D3": "error", "D4": "error",
    "D5": "error", "D6": "error", "D7": "error",
    "W1": "error", "W2": "error", "W3": "error", "W4": "error",
    "W5": "error", "W6": "error", "W7": "error", "W8": "error",
    "W9": "warning", "W10": "error", "W11": "warning",
    "T1": "error", "T2": "warning", "T3": "warning", "T4": "warning",
    "V1": "error", "V2": "error", "V3": "error", "V4": "warning",
    "A1": "warning", "A2": "warning", "A3": "warning",
    "A4": "warning", "A5": "warning", "A6": "warning",
    "A7": "warning", "A8": "warning",
    "L1": "error", "L2": "error", "L3": "error",
    "P1": "error",
}


# @trace docs/ru/checking.md#levels,ADR-012
def level_of_project(cfg):
    """Уровень кода по ключу codes проекта (ADR-012); None — по умолчанию.

    C1 и V1 не настраиваются: их уровень задаёт правило.
    """
    def resolve(code):
        if code in ("C1", "V1"):
            return None
        return cfg.get("codes", {}).get(code)
    return resolve


class Report:
    """Находки проверок.

    У каждой находки есть subject — устойчивая суть без чисел и формулировки:
    цель ссылки (D1, D5, D7, W6, W9), якорь (D2), имя поля шапки (W3), раздел (W8),
    цель метки (T1), номер работы и так далее. По (code, file, subject)
    ошибки сопоставляются с базовой линией, поэтому ни номер строки, ни текст
    сообщения её не ломают.
    """

    def __init__(self, level_of=None):
        # level_of(code) — уровень кода по настройкам проекта (ключ codes),
        # None — уровень по умолчанию из CODE_LEVELS
        self.items = []
        self._level_of = level_of

    def add(self, level, code, path, line, msg, subject=""):
        self.items.append((str(path), line or 0, level, code, msg, subject))

    def finding(self, code, path, line, msg, subject="", level=None):
        """Находка с уровнем: исключение по правилу (level), ключ codes
        проекта, иначе таблица CODE_LEVELS. «off» — находки нет."""
        if level is None:
            level = self._level_of(code) if self._level_of else None
        wanted = level if level is not None else CODE_LEVELS[code]
        if wanted == "off":
            return
        self.add(wanted if wanted in ("E", "W") else ("E" if wanted == "error" else "W"),
                 code, path, line, msg, subject)

    def count(self, level):
        return sum(1 for i in self.items if i[2] == level)

    def dump(self):
        for path, line, level, code, msg, _ in sorted(self.items):
            loc = "%s:%d" % (path, line) if line else path
            head = loc + ": " if loc else ""
            print("%s[%s %s] %s" % (head, tr("checker.report.error") if level == "E" else tr("checker.report.warning"),
                                    code, msg))


# --- Вывод ------------------------------------------------------------------
#
# Три формы: text — строки для человека (по умолчанию), json — один объект
# для инструментов и CI, github — аннотации GitHub Actions. Находки обеих
# строгостей живут в одном списке Report; в JSON ошибки и предупреждения
# разложены по двум ключам, у каждой находки есть subject — то, по чему её
# сопоставляют с базовой линией.
#
# Коды возврата: 0 — чисто, 1 — новые ошибки (или предупреждения при
# --strict), 2 — неверный запуск или C1 (настройкам нельзя доверять).

# @trace docs/ru/commands.md#output
FORMATS = ("text", "json", "github")
JSON_SCHEMA = 1


def finding_item(item):
    """Находка Report в форме JSON: file — путь, а не поле структуры nodes."""
    path, line, _level, code, msg, subject = item
    return {"code": code, "file": path, "line": line,
            "subject": subject, "message": msg}


def json_output(errors, warnings, baseline=None, summary=None, structure=None):
    """Один объект JSON. С --structure в нём появляется ключ structure."""
    payload = {
        "schema": JSON_SCHEMA,
        "version": __version__,
        "errors": errors,
        "warnings": warnings,
        "baseline": {"known": baseline[0] if baseline else 0,
                     "fixed": baseline[1] if baseline else 0},
        "summary": summary if summary is not None else {
            "pages": 0, "docs": 0, "tags": 0,
            "errors": len(errors), "warnings": len(warnings)},
    }
    if structure is not None:
        payload["structure"] = structure
    return payload


def gh_escape(text, prop=False):
    """Экранирование по правилам команд GitHub Actions.

    В данных экранируются %, перевод строки и возврат каретки; в значениях
    свойств ещё : и , — иначе аннотация развалится на части.
    """
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        text = text.replace(":", "%3A").replace(",", "%2C")
    return text


def gh_lines(items):
    """Строки аннотаций GitHub Actions: ::error и ::warning.

    Формат: `::error file=…,line=…,title=<код>::<сообщение>`; без файла —
    без параметра file, при line = 0 — без line.
    """
    lines = []
    for path, line, level, code, msg, _subject in sorted(items):
        props = []
        if path:
            props.append("file=%s" % gh_escape(path, prop=True))
        if line:
            props.append("line=%d" % line)
        props.append("title=%s" % gh_escape(code, prop=True))
        lines.append("::%s %s::%s" % ("error" if level == "E" else "warning",
                                      ",".join(props), gh_escape(msg)))
    return lines


def print_gh(items):
    for line in gh_lines(items):
        print(line)
