"""support.py — каркас тестов lipi.

Разворачивает проекты во временном каталоге, запускает чекер подпроцессом
(`-B`: без .pyc) и разбирает JSON; умеет init/collect/doctor и
git-репозитории с коммитами по датам. Импортируется всеми модулями
tests/test_*.py.

Запуск: python3 -m unittest discover -s tests   (в корне lipi)
"""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
LIPI = HERE.parent
SRC = LIPI / "src" / "lipi"
if str(SRC.parent) not in sys.path:
    sys.path.insert(0, str(SRC.parent))
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (SRC / "__init__.py").read_text(encoding="utf-8")).group(1)
CHECK = SRC / "check.py"
INIT = SRC / "init.py"
COLLECT = SRC / "collect.py"
DOCTOR = SRC / "doctor.py"
MIGRATE = SRC / "migrate.py"
CLI = SRC / "cli.py"
PY = [sys.executable, "-B"]
TAG = "@" + "trace"          # по частям, чтобы чекер не принял за метку

# Пути файлов lipi в проекте (ADR-009). CHECK_REL — тестовый скрипт,
# имитирующий локальную копию чекера (ADR-010).
LIPI_DIR = ".agents/lipi"
CHECK_REL = LIPI_DIR + "/check.py"
LOCK_REL = LIPI_DIR + "/lipi.lock"
BASE_REL = LIPI_DIR + "/baseline.json"
# необязательный файл lipi: задание CI GitHub Actions (ADR-009)
CI_REL = ".github/workflows/lipi.yml"

TYPE_DIRS = {"pln": "plan", "iss": "issue", "dsc": "discussion", "adr": "adr", "aud": "audit"}


def localized(english, russian):
    from lipi.i18n import current_language
    return russian if current_language() == "ru" else english


def language_env(profile, language):
    """Isolate a CLI call's personal settings from the test runner's."""
    w(profile / ".config/lipi/config.json", json.dumps({"language": language}))
    return child_environment({"HOME": str(profile), "USERPROFILE": str(profile)})


def freeze_workflow_clock(stamp, utc_offset=0):
    """Фиксирует момент и местную зону без изменения часового пояса процесса."""
    instant = datetime.fromisoformat(stamp)
    local_zone = timezone(timedelta(hours=utc_offset))

    def now(zone=None):
        return instant.astimezone(zone if zone is not None else local_zone)

    return patch("lipi.checker.workflow_layout.datetime", **{"now.side_effect": now})


@contextmanager
def time_budget(test, label):
    """Enforce the two-second CLI budget on the selected CI runner."""
    if os.environ.get("LIPI_TEST_TIMING") != "1":
        yield
        return
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    print(f"\n{label}: {elapsed:.3f}s")
    test.assertLess(elapsed, 2.0, label)


def child_environment(overrides=None):
    """A test invokes a local command unless it explicitly sets CI."""
    child_env = os.environ.copy()
    child_env.pop("CI", None)
    if overrides is not None:
        child_env.update(overrides)
    return child_env


def run(cmd, cwd=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, env=child_environment(env))
    return p.returncode, p.stdout.decode("utf-8", "replace")


def check(root, *args, env=None):
    """Чекер установленного lipi по проекту root: (код возврата, вывод).

    Проект кода lipi не содержит (ADR-010): запускается чекер пакета с
    --root, как это делает команда lipi check.
    """
    return run(PY + [str(CHECK), "--root", str(root)] + list(args),
               cwd=str(root), env=env)


def check_json(root, *args):
    """check с --format json: (код возврата, объект или None).

    Формат подставляется сам; явный --format в args (например, после new)
    не дублируется.
    """
    if "--format" not in args:
        args = ("--format", "json") + args
    code, out = check(root, *args)
    try:
        return code, json.loads(out)
    except ValueError:
        return code, None


def init(root, *args):
    return run(PY + [str(INIT), str(root)] + list(args))


def collect(*projects):
    return run(PY + [str(COLLECT)] + [str(p) for p in projects])


def doctor(cwd, *args):
    """lipi doctor в каталоге cwd: (код возврата, вывод)."""
    return run(PY + [str(DOCTOR)] + list(args), cwd=str(cwd))


def cli(cwd, *args):
    return run(PY + [str(CLI)] + list(args), cwd=str(cwd))


def w(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def wb(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def sub(path, old, new):
    path = Path(path)
    t = path.read_text(encoding="utf-8")
    assert old in t, "%s: нет «%s»" % (path, old)
    path.write_text(t.replace(old, new), encoding="utf-8")


def found(out, code):
    """Есть ли в выводе чекера строка с кодом проверки («[ошибка D1]»)."""
    return " %s]" % code in out


def doc(root, prefix, num="001"):
    """Путь рабочего документа с номером (первый подходящий)."""
    return next((root / "workflow" / TYPE_DIRS[prefix]).rglob("%s-%s-*" % (prefix, num)))


def header_set(root, prefix, fields, num="001"):
    """Заменяет или добавляет строки «- Ключ: значение» в шапке документа.

    Новые ключи вставляются после имеющихся строк шапки, чтобы
    Page.header() видел их вместе с прежними полями.
    """
    p = doc(root, prefix, num)
    lines = p.read_text(encoding="utf-8").split("\n")
    done = set()
    out = []
    for s in lines:
        m = s.strip().startswith("- ") and ": " in s
        key = s.strip()[2:].split(":", 1)[0].strip() if m else None
        if key in fields:
            out.append("- %s: %s" % (key, fields[key]))
            done.add(key)
            continue
        out.append(s)
    missing = [k for k in fields if k not in done]
    if missing:
        start = next((i for i, line in enumerate(out) if line.startswith("- ") and ": " in line), 2)
        pos = start
        while pos < len(out) and out[pos].startswith("- ") and ": " in out[pos]:
            pos += 1
        out[pos:pos] = ["- %s: %s" % (k, fields[k]) for k in missing]
    p.write_text("\n".join(out), encoding="utf-8")


def header_del(root, prefix, key, num="001"):
    p = doc(root, prefix, num)
    lines = [s for s in p.read_text(encoding="utf-8").split("\n")
             if not (s.strip().startswith("- ") and ": " in s
                     and s.strip()[2:].split(":", 1)[0].strip() == key)]
    p.write_text("\n".join(lines), encoding="utf-8")


def reindex(root):
    return check(root, "--write-index")


def set_lock_version(root, version):
    """Версия в lock-файле проекта; отпечатки файлов не меняются."""
    path = Path(root) / LOCK_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["lipi"] = version
    w(path, json.dumps(data, sort_keys=True, indent=2) + "\n")


def set_config(root, **fields):
    cfg_path = root / "lipi.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.update(fields)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(root, *args, env=None):
    return run(["git", "-C", str(root)] + list(args), env=env)


def git_init(root, name="tester"):
    git(root, "init", "-q")
    git(root, "config", "user.name", name)
    git(root, "config", "user.email", name + "@example.com")


def commit(root, msg="commit", date="2026-01-01T10:00:00"):
    """Коммит с заданным временем автора и коммитера (для --staged/--diff и blame)."""
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    git(root, "add", "-A")
    return git(root, "commit", "-q", "-m", msg, env=env)


def seed(root):
    """Небольшой правильный проект: страница с якорем, метка, план, замечание."""
    w(root / "docs" / "guide.md", "# Скидки\n\n## Наибольшая <a id=\"max-discount\"></a>\n\nТекст.\n")
    sub(root / "docs" / "README.md", "| --- | --- |", "| --- | --- |\n| Скидки | [Скидки](guide.md#max-discount) |")
    w(root / "src" / "order.py", "# %s docs/guide.md#max-discount\ndef discount(o):\n    return max(o)\n" % TAG)
    assert check(root, "new", "pln", "Первый план")[0] == 0
    assert check(root, "new", "iss", "Первое замечание", "bug")[0] == 0
    # замечание «открыто»: раздел «Что наблюдается» обязателен (W8)
    sub(doc(root, "iss"), "## Observation", "## Observation\n\nТекст.\n")


def lipi_copy(dst):
    """Копия без истории Git, артефактов сборки и полного набора тестов."""
    shutil.copytree(LIPI, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "tests", "*.pyc", "build", "dist", "*.egg-info"))
    (Path(dst) / "tests").mkdir()
    for name in ("check_package.py", "test_move_batch.py"):
        shutil.copy2(LIPI / "tests" / name, Path(dst) / "tests" / name)


class Case(unittest.TestCase):
    """Тест с «правильным» проектом lipi во временном каталоге.

    setUpClass разворачивает каркас и, если seed_project, наполняет его;
    каждый тест получает копию через self.project().
    """
    base_args = ()
    seed_project = True
    _counter = itertools.count()

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lipi-test-"))
        cls.base = cls.tmp / "base"
        cls.base.mkdir()
        code, out = init(cls.base, *cls.base_args)
        if code != 0:
            raise AssertionError("init не прошёл: %s" % out)
        if cls.seed_project:
            seed(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self, name="case"):
        root = self.tmp / ("%s-%d" % (name, next(type(self)._counter)))
        shutil.copytree(self.base, root)
        return root
