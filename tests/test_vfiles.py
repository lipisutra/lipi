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
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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


# @trace docs/ru/codes.md#v4
class TestV4(support.Case):
    seed_project = False

    def test_equal_version_matches_repeat_init(self):
        root = self.project()
        # Model an editable install: change the package templates under the
        # running command while keeping its version and project lock intact.
        package = root.parent / "editable" / "lipi"
        shutil.copytree(support.SRC, package)
        templates = package / "locale/en/templates"
        common = templates / "lipi/common"
        with (common / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\nUpdated managed rule.\n")
        support.w(common / "added.md", "# Added rule\n")
        (common / "workflow.md").unlink()
        support.w(templates / "seed/common/AGENTS.md", "# New starter\n")
        support.w(common / "ci/github.yml", "name: changed\n")

        def cli(*args):
            return support.run(support.PY + [str(package / "cli.py"), *args], cwd=root)

        def findings():
            status, output = cli("check", "--format", "json")
            self.assertEqual(status, 0, output)
            return {item["file"]: item["message"] for item in json.loads(output)["warnings"]
                    if item["code"] == "V4"}

        before = (root / support.LOCK_REL).read_bytes()
        retired = ".agents/lipi/workflow.md"
        kept = (root / retired).read_bytes()
        warnings = findings()
        self.assertEqual(set(warnings), {LIPI_README, ".agents/lipi/added.md", retired})
        self.assertIn("removes its lock entry", warnings[retired])
        self.assertIn("keeps the file", warnings[retired])
        self.assertTrue(all(support.VERSION in msg for msg in warnings.values()))
        status, output = cli("init", "--dry-run")
        self.assertEqual(status, 0, output)
        for name in warnings:
            self.assertIn(name, output)
        self.assertEqual((root / support.LOCK_REL).read_bytes(), before)
        status, output = cli("init")
        self.assertEqual(status, 0, output)
        self.assertEqual(findings(), {})
        self.assertEqual((root / retired).read_bytes(), kept)
        self.assertNotIn(retired, json.loads((root / support.LOCK_REL).read_text())["files"])
        self.assertFalse((root / support.CI_REL).exists())

    def test_old_deployment_and_local_edits(self):
        root = self.project()
        lockfile = root / support.LOCK_REL
        lock = json.loads(lockfile.read_text())
        lock["lipi"] = "1.0.0"
        lock["files"][LIPI_README] = hashlib.sha256(b"old package rules").hexdigest()
        support.w(lockfile, json.dumps(lock))
        support.w(root / LIPI_README, "local edits")
        status, data = support.check_json(root)
        self.assertEqual(status, 1, data)
        self.assertIn(("V3", LIPI_README), {(i["code"], i["file"]) for i in data["errors"]})
        warning, = [i for i in data["warnings"] if i["code"] == "V4"]
        self.assertEqual(warning["file"], LIPI_README)
        self.assertIn("lipi init --dry-run", warning["message"])
        self.assertIn("save any local edits", warning["message"])

    def test_current_file_with_old_lock_only_updates_lock(self):
        root = self.project()
        target = root / LIPI_README
        original_mtime = target.stat().st_mtime_ns
        lockfile = root / support.LOCK_REL
        lock = json.loads(lockfile.read_text())
        lock["files"][LIPI_README] = hashlib.sha256(b"old rules").hexdigest()
        support.w(lockfile, json.dumps(lock))

        status, data = support.check_json(root)
        self.assertEqual(status, 1, data)
        self.assertIn(("V3", LIPI_README), {(i["code"], i["file"]) for i in data["errors"]})
        warning, = [i for i in data["warnings"] if i["code"] == "V4"]
        self.assertEqual(warning["file"], LIPI_README)
        self.assertIn("only its lock entry", warning["message"])
        self.assertNotIn("save any local edits", warning["message"])

        status, output = support.init(root)
        self.assertEqual(status, 0, output)
        self.assertEqual(target.stat().st_mtime_ns, original_mtime)
        status, data = support.check_json(root)
        self.assertEqual(status, 0, data)
        self.assertFalse(any(i["code"] == "V4" for i in data["warnings"]))

    def test_alternate_config_sets_level_but_uses_init_manifest(self):
        root = self.project()
        target = ".agents/lipi/documentation.md"
        lockfile = root / support.LOCK_REL
        lock = json.loads(lockfile.read_text())
        support.w(root / target, "old rules\n")
        lock["files"][target] = sha256_path(root / target)
        support.w(lockfile, json.dumps(lock))
        alternate = root.parent / "check-settings.json"
        cfg = json.loads((root / "lipi.json").read_text())
        cfg.update(enforce=True, codes={"V4": "error"})
        support.w(alternate, json.dumps(cfg))

        status, data = support.check_json(root, "--config", str(alternate))
        self.assertEqual(status, 1, data)
        self.assertEqual([i["file"] for i in data["errors"] if i["code"] == "V4"], [target])
        self.assertFalse(any(i["code"] == "V4" for i in data["warnings"]))

        status, output = support.init(root)
        self.assertEqual(status, 0, output)
        status, data = support.check_json(root, "--config", str(alternate))
        self.assertEqual(status, 0, data)
        self.assertFalse(any(i["code"] == "V4" for i in data["warnings"]))

    def test_git_workflow_symlink_loop_skips_v4(self):
        root = self.project()
        support.git_init(root)
        support.set_config(root, workflow=None)
        status, output = support.check(root)
        self.assertEqual(status, 0, output)
        self.assertTrue(support.found(output, "V4"), output)

        workflow = root / "workflow"
        shutil.rmtree(workflow)
        workflow.symlink_to("workflow", target_is_directory=True)
        status, output = support.check(root)
        self.assertEqual(status, 0, output)
        self.assertFalse(support.found(output, "V4"), output)

    def test_ci_ownership_and_codes(self):
        root = self.project()
        status, output = support.init(root, "--ci", "github")
        self.assertEqual(status, 0, output)
        lockfile = root / support.LOCK_REL
        lock = json.loads(lockfile.read_text())
        self.assertFalse(lock["enforce"])
        support.w(root / support.CI_REL, "name: old\n")
        lock["files"][support.CI_REL] = sha256_path(root / support.CI_REL)
        support.w(lockfile, json.dumps(lock))
        for level, key, expected_status in (("warning", "warnings", 0), ("error", "errors", 1),
                                             ("off", "warnings", 0)):
            with self.subTest(level=level):
                support.set_config(root, codes={"V4": level})
                status, data = support.check_json(root)
                self.assertEqual(status, expected_status, data)
                self.assertEqual([i["file"] for i in data[key] if i["code"] == "V4"],
                                 [] if level == "off" else [support.CI_REL])

    def test_version_and_valid_lock_boundaries(self):
        root = self.project()
        lockfile = root / support.LOCK_REL
        lock = json.loads(lockfile.read_text())
        # Deploy a different generation while keeping the working file clean.
        support.w(root / LIPI_README, "old rules")
        lock["files"][LIPI_README] = sha256_path(root / LIPI_README)
        major = int(support.VERSION.split(".")[0])
        for version in (f"{major}.999.0", f"{major - 1}.0.0", f"{major + 1}.0.0"):
            with self.subTest(version=version):
                lock["lipi"] = version
                support.w(lockfile, json.dumps(lock))
                _, data = support.check_json(root)
                codes = {i["code"] for i in data["warnings"] + data["errors"]}
                self.assertIn("V1", codes)
                self.assertNotIn("V4", codes)
        lock["lipi"] = support.VERSION
        for files in ({}, {LIPI_README: "invalid digest"}):
            support.w(lockfile, json.dumps(dict(lock, files=files)))
            _, data = support.check_json(root)
            self.assertFalse(any(i["code"] == "V4" for i in data["warnings"] + data["errors"]))


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
