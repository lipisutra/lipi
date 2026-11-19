"""Общие имена, пути и шаблоны чекера."""
import re

# --- Соглашения (меняются только вместе с текстом правил) --------------------

TYPES = {            # префикс -> (каталог, название)
    "pln": ("plan", "checker.conventions.plan"),
    "aud": ("audit", "checker.conventions.audit"),
    "dsc": ("discussion", "checker.conventions.discussion"),
    "adr": ("adr", "checker.conventions.decision"),
    "iss": ("issue", "checker.conventions.issue"),
}
STATUSES = {
    "pln": ["new", "in progress", "pending acceptance", "deferred", "completed", "canceled"],
    "iss": ["open", "in progress", "closed"],
    "adr": ["proposed", "accepted", "superseded", "rejected"],
    "dsc": ["open", "closed"],
}
FINAL = {"completed", "canceled", "closed", "superseded", "rejected"}
NEED_RESULT = {("pln", "completed"), ("pln", "canceled"), ("iss", "closed")}
# W8: статусы, при которых разделы обязательны и непусты
REQUIRED_SECTIONS = {
    ("iss", "open"): ["Observation"],
    ("iss", "in progress"): ["Observation"],
    ("pln", "in progress"): ["Purpose", "Completion criteria"],
    ("pln", "pending acceptance"): ["Purpose", "Completion criteria"],
}
ISSUE_KINDS = ["bug", "friction", "request", "question"]
K_CREATED, K_UPDATED, K_STATUS, K_RESULT, K_KIND = (
    "Created", "Updated", "Status", "Result", "Kind")
K_ADDRESSEE, K_SOURCE = "Recipient", "Source"   # замечание к самому lipi и его происхождение
K_REFINES = "Refines"
K_DUE = "Due"
K_CLOSED = "Closed"
DECISION_HEADING = "Decision"
SOURCE_EXTERNAL = "external"
HISTORY_DIR = "history"
MASTERPLAN, INDEX = "masterplan.md", "INDEX.md"
# Замечания к lipi в проекте без рабочих материалов; в указатель не входят.
FEEDBACK = ".agents/lipi-feedback"
# Файлы lipi: правила, lock-файл, базовая линия и (если подключён) шаблон CI.
# Они принадлежат lipi (ADR-009): init заменяет управляемые файлы, проект их не
# правит, а целостность правил и шаблона CI проверяет V3 по отпечаткам в
# lock-файле. Копии чекера в проекте нет (ADR-010).
LIPI_DIR = ".agents/lipi"
LIPI_README = LIPI_DIR + "/README.md"
CONFIG_NAME = "lipi.json"


SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target",
             ".venv", "venv", "__pycache__", ".idea", ".vscode", ".next",
             "coverage", ".gradle", ".cache", ".agents"}
CODE_EXT = ("py|js|jsx|mjs|cjs|ts|tsx|go|java|kt|kts|rb|php|cs|rs|swift|sql|"
            "c|cc|cpp|h|hpp|m|vue|svelte|dart|scala|sh|lua|ex|exs")
MAX_CODE_FILE = 1_000_000

RE_DOC_NAME = re.compile(r"^(%s)-(\d{3,})-([a-z0-9]+(?:-[a-z0-9]+)*)$" % "|".join(TYPES))
RE_DECISION_NAME = re.compile(r"^(?:adr-)?(\d+)(?:-(.+))?$", re.I)
RE_DOC_REF = re.compile(r"(?<![A-Za-z0-9-])(%s)-(\d{3,})(?![0-9])" % "|".join(TYPES), re.I)
RE_ANCHOR = re.compile(r'<a\s+id="([^"]*)"[^>]*>')
RE_LINK = re.compile(r'\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
RE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
RE_TRACE = re.compile(r"@trace\s+((?=\S)[^\s,]*(?:\s*,\s*[^\s,]*)*)")
RE_COVERS = re.compile(r"<!--\s*covers:\s*([^>]*?)\s*-->")
RE_HEADER = re.compile(r"^- ([^:]+):\s*(.*)$")
# markdown-ссылка на правила lipi; якорь в цели допустим, упоминание текстом — нет
RE_LIPI_LINK = re.compile(r"\]\(\s*<?%s(?:#[^)\s>]*)?>?\s*\)" % re.escape(LIPI_README))
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_TEST_NAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|Tests?\.[A-Za-z]+$)")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}


LOCK_NAME = LIPI_DIR + "/lipi.lock"
BASE_NAME = LIPI_DIR + "/baseline.json"
