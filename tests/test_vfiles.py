"""test_vfiles.py — файлы lipi отдельно от файлов проекта (ADR-009).

Проверки файлов .agents/lipi/:

- V2: в AGENTS.md нет ссылки на .agents/lipi/README.md — ошибка быстрого
  режима; упоминание пути текстом ссылкой не считается.
- V3: нет отпечатков в lock-файле или правило lipi либо шаблон CI не совпадает
  с отпечатком — ошибка быстрого режима.
- При наличии lock-файла обе проверки работают, даже если отпечатков нет.
- V3 сверяет любую запись lock-файла, включая пути вне шаблонов.
- init сохраняет существующий AGENTS.md и просит добавить ссылку вручную;
  новая заготовка уже содержит ссылку.

Запуск: python3 -m unittest tests.test_vfiles
"""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

LIPI_README = ".agents/lipi/README.md"
LIPI_FILES = (".agents/lipi/README.md", ".agents/lipi/documentation.md",
              ".agents/lipi/workflow.md")
# подстрока, по которой V2 узнаёт markdown-ссылку на правила lipi
AGENTS_LINK = "](" + LIPI_README + ")"


def sha256_path(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestV2(support.Case):
    """V2: в AGENTS.md есть ссылка на .agents/lipi/README.md."""

    def test_link_present(self):
        """Ссылка есть — V2 молчит."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V2"), out)

    def test_no_link(self):
        """Ссылки нет (путь упомянут текстом) — ошибка V2."""
        root = self.project()
        support.sub(root / "AGENTS.md", AGENTS_LINK, LIPI_README)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)
        self.assertIn(support.localized('AGENTS.md lacks a link to the lipi rules at .agents/lipi/README.md', "в AGENTS.md нет ссылки на .agents/lipi/README.md"), out)

    def test_link_to_other_file(self):
        """Ссылка на другой файл вместо правил lipi — ошибка V2."""
        root = self.project()
        support.sub(root / "AGENTS.md", AGENTS_LINK, "](docs/README.md)")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)

    def test_no_agents_md(self):
        """Файла AGENTS.md нет — ошибка V2."""
        root = self.project()
        (root / "AGENTS.md").unlink()
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)

    def test_without_lock_v2_silent(self):
        """Lock-файла нет (проект до развёртывания) — V2 молчит."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        (root / "AGENTS.md").unlink()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V2"), out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_v2_is_quick_error(self):
        """V2 — ошибка обычного (быстрого) режима, не только аудита."""
        root = self.project()
        support.sub(root / "AGENTS.md", AGENTS_LINK, LIPI_README)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V2"), out)


class TestV3(support.Case):
    """V3: правила lipi совпадают с отпечатками в .agents/lipi/lipi.lock."""

    def test_lipi_files_match_lock(self):
        """Свежий проект: правила совпадают с lock — V3 молчит."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_changed_lipi_file(self):
        """Файл lipi изменён на месте — ошибка V3 с подсказкой про замечание."""
        root = self.project()
        target = root / support.LIPI_DIR / "README.md"
        support.w(target, target.read_text(encoding="utf-8") + "\nправка на месте\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)
        self.assertIn(support.localized('%s: fingerprint differs from lipi.lock', "%s: не совпадает с отпечатком lipi") % LIPI_README, out)
        self.assertIn(support.localized('Open an issue for lipi to request a change to its rules.', "правило lipi не правится на месте, заведите замечание к lipi"), out)

    def test_deleted_lipi_file(self):
        """Файл lipi удалён — ошибка V3 с его путём."""
        root = self.project()
        (root / support.LIPI_DIR / "documentation.md").unlink()
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)
        self.assertIn(support.localized('.agents/lipi/documentation.md: fingerprint differs from lipi.lock', ".agents/lipi/documentation.md: не совпадает с отпечатком lipi"),
                      out)

    def test_without_lock_v3_silent(self):
        """Lock-файла нет — V3 не срабатывает, даже если файл lipi изменён."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        target = root / support.LIPI_DIR / "README.md"
        support.w(target, target.read_text(encoding="utf-8") + "\nправка на месте\n")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_v3_is_quick_error(self):
        """V3 — ошибка обычного (быстрого) режима, не только аудита."""
        root = self.project()
        target = root / support.LIPI_DIR / "workflow.md"
        support.w(target, target.read_text(encoding="utf-8") + "\nправка на месте\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)

    def test_lock_uses_new_paths(self):
        """В lock — только правила lipi: копии чекера в нём больше нет."""
        root = self.project()
        lock = json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))
        self.assertEqual(set(lock["files"]), set(LIPI_FILES))
        self.assertNotIn(support.CHECK_REL, lock["files"])
        for name, digest in lock["files"].items():
            self.assertEqual(sha256_path(root / name), digest, name)


class TestLipiGate(support.Case):
    """V2/V3 работают при наличии lock-файла."""

    def write_empty_lock(self, root):
        lock = json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))
        lock["files"] = {}
        support.w(root / support.LOCK_REL, json.dumps(lock, indent=2) + "\n")

    def test_no_lock_checks_silent(self):
        """Lock-файла нет — V2 и V3 молчат, даже если проект испорчен."""
        root = self.project()
        (root / support.LOCK_REL).unlink()
        (root / "AGENTS.md").unlink()
        target = root / support.LIPI_DIR / "README.md"
        support.w(target, target.read_text(encoding="utf-8") + "\nправка на месте\n")
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V2"), out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_empty_lock_reports_v3(self):
        """Пустые files дают ошибку V3 при исправном AGENTS.md."""
        root = self.project()
        self.write_empty_lock(root)
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertIn(support.LOCK_REL + support.localized(': [error V3] lipi.lock has no file fingerprints. Run lipi init.', ": [ошибка V3] в lock-файле нет отпечатков "
                      "файлов lipi — выполните lipi init"), out)
        self.assertFalse(support.found(out, "V2"), out)

    def test_empty_lock_runs_v2(self):
        """V2 проверяет ссылку в AGENTS.md при пустых files."""
        root = self.project()
        self.write_empty_lock(root)
        (root / "AGENTS.md").unlink()
        code, out = support.check(root)
        self.assertTrue(support.found(out, "V2"), out)
        self.assertEqual(code, 1, out)

    def test_valid_deployment_checks_silent(self):
        """В исправном развёртывании V2 и V3 молчат."""
        root = self.project()
        code, out = support.check(root)
        self.assertEqual(code, 0, out)
        self.assertFalse(support.found(out, "V2"), out)
        self.assertFalse(support.found(out, "V3"), out)

    def test_checker_record_is_checked(self):
        """Отпечаток check.py сверяется на общих основаниях."""
        root = self.project()
        copy = root / support.CHECK_REL
        support.wb(copy, b"import sys\nsys.exit(0)\n")
        lock = json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))
        lock["files"][support.CHECK_REL] = sha256_path(copy)
        support.w(root / support.LOCK_REL, json.dumps(lock, indent=2) + "\n")
        # Правка файла с отпечатком в lock — ошибка V3, независимо от имени.
        support.wb(copy, "import sys\nsys.exit(0)\n# правка\n".encode("utf-8"))
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)
        self.assertIn(support.CHECK_REL + support.localized(': fingerprint differs from lipi.lock', ": не совпадает с отпечатком lipi"), out)

    def test_v3_still_catches_rules(self):
        """Правило всё так же сверяется, даже когда в lock есть запись о копии."""
        root = self.project()
        copy = root / support.CHECK_REL
        support.wb(copy, b"import sys\nsys.exit(0)\n")
        lock = json.loads((root / support.LOCK_REL).read_text(encoding="utf-8"))
        lock["files"][support.CHECK_REL] = sha256_path(copy)
        support.w(root / support.LOCK_REL, json.dumps(lock, indent=2) + "\n")
        target = root / support.LIPI_DIR / "README.md"
        support.w(target, target.read_text(encoding="utf-8") + "\nправка на месте\n")
        code, out = support.check(root)
        self.assertEqual(code, 1, out)
        self.assertTrue(support.found(out, "V3"), out)


class TestInitLink(unittest.TestCase):
    """init: AGENTS.md проекта сохраняется, новая заготовка содержит ссылку."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lipi-vfiles-"))
        self.root = self.tmp / "root"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agents(self):
        return (self.root / "AGENTS.md").read_text(encoding="utf-8")

    def test_existing_agents_is_preserved(self):
        """Существующий AGENTS.md сохраняется при первом и повторном init."""
        foreign = "# Мои правила\n\n- своё правило\n"
        support.w(self.root / "AGENTS.md", foreign)
        for _ in range(2):
            code, out = support.init(self.root)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.agents(), foreign)
            self.assertIn(support.localized('Add a link to the rules in AGENTS.md', "добавьте вручную в AGENTS.md ссылку на правила"), out)
        # Сохранность файла не отменяет V2: проекту всё ещё нужна ссылка.
        code, out = support.check(self.root, "--no-baseline")
        self.assertTrue(support.found(out, "V2"), out)

    def test_existing_link_is_not_touched(self):
        """Ссылка уже есть — AGENTS.md не меняется и в выводе нет дописывания."""
        text = "# Мои правила\n\nПравила lipi: [правила](%s).\n" % LIPI_README
        support.w(self.root / "AGENTS.md", text)
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.agents(), text)
        self.assertNotIn("дописана ссылка на правила lipi", out)

    def test_init_without_agents_creates_seed(self):
        """AGENTS.md нет — создаётся заготовка со ссылкой, дописывать нечего."""
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "AGENTS.md").is_file())
        self.assertIn(LIPI_README, self.agents())
        self.assertNotIn("дописана ссылка на правила lipi", out)

    def test_manual_link_hint_points_to_lipi_rules(self):
        """Подсказка даёт ссылку, которую V2 примет в существующем AGENTS.md."""
        text = "мои правила\n"
        support.w(self.root / "AGENTS.md", text)
        code, out = support.init(self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.agents(), text)
        self.assertIn(support.localized('[rules](%s)', "[правила](%s)") % LIPI_README, out)
        support.w(self.root / "AGENTS.md", text + "\n[правила](%s).\n" % LIPI_README)
        code, out = support.check(self.root, "--no-baseline")
        self.assertFalse(support.found(out, "V2"), out)


if __name__ == "__main__":
    unittest.main()
