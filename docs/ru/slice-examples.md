# Примеры среза

Формы целей, состав блоков, предел и схема JSON — в [договоре среза](slice.md).
Для текстовых примеров выбран русский язык командой `lipi lang ru`.
В JSON служебные сообщения всегда английские.

**Раздел.** `lipi slice docs/pricing.md#threshold`:

В этом примере якорь стоит в абзаце: заголовок берётся из его текста и
сокращается по границе слова до 80 знаков с многоточием.

```text
docs/pricing.md#threshold — Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма сравнивается…
1 предупреждение · 1 решение · 1 правило · 2 точки входа · 5 мест в коде (3 слоя) · 2 теста · 1 открытая работа
устаревание проверено для 7 из 7 мест

Сигналы
  ! A4  src/domain/discount.py:12 — код менялся 2026-11-12 09:14:00 UTC, позже раздела (2026-10-03 18:40:00 UTC)
  · ISS-007 open — Порог не учитывает возвраты (ссылается на раздел)
Соблюдать
  ADR-018 accepted — Скидка считается от суммы без доставки (link)
  .agents/architecture.md#money — Деньги только в Money (mark)
Выдержка
  Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма
  сравнивается после округления, см. [Округление](#rounding).
С чего начинать
  src/api/orders.py:88  def post_order(request)  [api]
  src/app/checkout.py:40  def apply_discount(order)  [app]
Места в коде
  src/app/settings.py:21  DISCOUNT_THRESHOLD = Money(10_000)  [app]
  src/domain/discount.py:12  class DiscountPolicy:  [domain]
  src/domain/discount.py:57  def threshold_for(customer):  [domain]
Тесты
  tests/test_checkout.py:30  def test_discount_applied():
  tests/test_discount.py:8  def test_threshold_boundary():
Контекст
  docs/orders.md#total — Сумма заказа
  docs/pricing.md#rounding — Округление
```

То же в JSON (`--format json`) — те же элементы:

```json
{"schema": 1,
 "target": {"kind": "section", "target": "docs/pricing.md#threshold", "title": "Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма сравнивается…", "found": "exact"},
 "summary": {"errors": 0, "warnings": 1, "decisions": 1, "rules": 1, "concepts": 0, "entry": 2, "code": 5, "layers": 3, "tests": 2, "open_work": 1, "targets": 0},
 "blocks": [
  {"kind": "signals", "omitted": 0, "hint": [], "items": [
    {"code": "A4", "level": "warning", "message": "code changed on 2026-11-12 09:14:00 UTC, after the section (2026-10-03 18:40:00 UTC)", "target": "docs/pricing.md#threshold", "path": "src/domain/discount.py", "line": 12},
    {"code": null, "level": "info", "message": "ISS-007 open — Порог не учитывает возвраты (links to the section)", "target": "ISS-007"}]},
  {"kind": "obey", "omitted": 0, "hint": [], "items": [
    {"target": "ADR-018", "title": "Скидка считается от суммы без доставки", "relation": "link", "status": "accepted"},
    {"target": ".agents/architecture.md#money", "title": "Деньги только в Money", "relation": "mark"}]},
  {"kind": "excerpt", "omitted": 0, "hint": [], "items": [
    {"text": "Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма\nсравнивается после округления, см. [Округление](#rounding).", "lines": 2, "cut": false}]},
  {"kind": "entry", "omitted": 0, "hint": [], "items": [
    {"path": "src/api/orders.py", "line": 88, "symbol": "def post_order(request)", "layer": "api", "via": "docs/pricing.md#threshold"},
    {"path": "src/app/checkout.py", "line": 40, "symbol": "def apply_discount(order)", "layer": "app", "via": "docs/pricing.md#threshold"}]},
  {"kind": "code", "omitted": 0, "hint": [], "items": [
    {"path": "src/app/settings.py", "line": 21, "symbol": "DISCOUNT_THRESHOLD = Money(10_000)", "layer": "app", "via": "docs/pricing.md#threshold"},
    {"path": "src/domain/discount.py", "line": 12, "symbol": "class DiscountPolicy:", "layer": "domain", "via": "docs/pricing.md#threshold"},
    {"path": "src/domain/discount.py", "line": 57, "symbol": "def threshold_for(customer):", "layer": "domain", "via": "docs/pricing.md#threshold"}]},
  {"kind": "tests", "omitted": 0, "hint": [], "items": [
    {"path": "tests/test_checkout.py", "line": 30, "symbol": "def test_discount_applied():", "layer": "tests"},
    {"path": "tests/test_discount.py", "line": 8, "symbol": "def test_threshold_boundary():", "layer": "tests"}]},
  {"kind": "context", "omitted": 0, "hint": [], "items": [
    {"target": "docs/orders.md#total", "title": "Сумма заказа", "relation": "link", "depth": 1},
    {"target": "docs/pricing.md#rounding", "title": "Округление", "relation": "link", "depth": 1}]}],
 "incomplete": false,
 "notes": [{"code": "staleness-full", "text": "checked 7 of 7 locations for staleness"}],
 "checks": {"staleness": {"state": "full", "checked": 7, "total": 7}}}
```

**Файл кода.** `lipi slice src/domain/discount.py` (строка об охвате проверки
устаревания в примере опущена):

```text
src/domain/discount.py — файл кода [domain]
1 предупреждение · 1 решение · 1 правило · 2 понятия · 4 места в коде (2 слоя) · 3 теста

Сигналы
  ! T3  src/domain/discount.py:80 — ISS-004 closed — проверьте, нужна ли связь; если это временный обход, его можно убрать
Соблюдать
  ADR-018 accepted — Скидка считается от суммы без доставки (mark)
  .agents/architecture.md#money — Деньги только в Money (mark)
Понятия
  docs/pricing.md#rounding — Округление (2 места в коде)
  docs/pricing.md#threshold — Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма сравнивается… (5 мест в коде)
Тесты
  tests/test_checkout.py:30  def test_discount_applied():
  tests/test_discount.py:8  def test_threshold_boundary():
  tests/test_discount.py:31  def test_rounding_half_up():
Места в коде
  src/api/orders.py:88  def post_order(request)  [api]
  src/app/checkout.py:40  def apply_discount(order)  [app]
  src/app/rounding.py:9  def round_total(amount):  [app]
  src/app/settings.py:21  DISCOUNT_THRESHOLD = Money(10_000)  [app]
```

**Работа.** `lipi slice ISS-007`:

```text
ISS-007 — Порог не учитывает возвраты (open)
1 решение · 1 правило · 2 места в коде (1 слой) · 1 цель

Соблюдать
  ADR-018 accepted — Скидка считается от суммы без доставки (link) — через docs/pricing.md#threshold
  .agents/architecture.md#money — Деньги только в Money (mark) — через docs/pricing.md#threshold
Места в коде
  src/domain/discount.py:64  def net_total(order):  [domain]
  src/domain/refunds.py:15  class RefundLedger:  [domain]
Цели работы
  docs/pricing.md#threshold — Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма сравнивается… (5 мест в коде)
```

Если работа ссылается на несколько целей с общим основанием, строка
«Соблюдать» одна; после «через» перечислены все цели. В JSON это, например:

```json
{"target": "ADR-018", "title": "Скидка считается от суммы без доставки", "relation": "link", "status": "accepted", "via": ["docs/pricing.md#rounding", "docs/pricing.md#threshold"]}
```

## Изменения кода <a id="diff"></a>

`lipi slice --staged`: изменилось одно объявление под меткой
`docs/pricing.md#threshold` и один участок без меток. Другие места и тесты
нужно просмотреть; срез не объявляет их неверными. Здесь A4 выключен:

```text
--staged — проверьте связанные места
1 решение · 1 понятие · 1 место в коде (1 слой) · 1 тест
проверьте связанные места, решения и тесты
изменения без меток: 1 место

Соблюдать
  ADR-018 accepted — Скидка считается от суммы без доставки (link)
Понятия
  docs/pricing.md#threshold — Порог скидки (2 места в коде)
Места в коде
  src/api/orders.py:88  def post_order(request)  [api]
Тесты
  tests/test_discount.py:8  def test_threshold_boundary():
```

У `target` в JSON: `{"kind": "diff", "target": "--staged", "title": "check related locations"}`;
у `checks.diff`: `{"mode": "staged", "base": null, "files": 1, "unmarked": 1}`.
Отбор элементов и предел — общие, см. [договор диффа](slice-diff.md).

**Пустой срез.** `lipi slice docs/pricing.md#refunds` — код возврата 0:

```text
docs/pricing.md#refunds — Возвраты
меток нет — ищите по коду
```

В JSON: `"blocks": []`, `"notes": [{"code": "no-marks", "text": "no trace markers. Search the code"}]`.

**Обрезка.** `lipi slice docs/orders.md#total` при 47 местах в коде:

```text
Места в коде
  src/domain/order.py:20  class Order:  [domain]
  ...
  показано 12 из 47; ещё — --only code, --layer domain|app|infra
```

В JSON у блока: `"omitted": 35, "hint": ["--only code", "--layer"]`, и
`"incomplete": true`.

**Цель не найдена.** `lipi slice скидк` — код возврата 1:

```text
цель «скидк» неоднозначна; кандидаты:
  docs/loyalty.md#tier-threshold — Скидка по уровню
  docs/pricing.md#threshold — Скидка 5% действует с суммы заказа 10 000 ₽ без доставки. Сумма сравнивается…
```

В JSON: `{"schema": 1, "error": "ambiguous", "query": "скидк", "candidates": [{"target": "...", "title": "..."}]}`;
у не найденной — `"error": "not-found"`.

## Подключённые репозитории <a id="repos"></a>

Примеры к [договору подключений](slice.md#repos).
SHA условные. Оба репозитория чистые; местный код ссылается на внешний раздел,
прочих связей нет. `lipi slice core::docs/api.md#request`, код возврата 0:

```text
core::docs/api.md#request — Запрос
1 место в коде (1 слой, 1 репозиторий)
источники: свой aaaaaaa, чистый; core bbbbbbb, чистый
Доступные источники: свой, core.
межрепозиторное устаревание не проверено

Выдержка
  ## Запрос

  Запрос содержит идентификатор.
Места в коде
  src/client.py:2  def request():  [api]
```

Полный JSON того же ответа:

```json
{"schema":1,
 "target":{"repo":"core","kind":"section","target":"docs/api.md#request","title":"Запрос","found":"exact"},
 "summary":{"errors":0,"warnings":0,"decisions":0,"rules":0,"concepts":0,"entry":0,"code":1,"layers":1,"tests":0,"open_work":0,"targets":0,"repos":1},
 "blocks":[
  {"kind":"excerpt","items":[{"text":"## Запрос\n\nЗапрос содержит идентификатор.","lines":3,"cut":false}],"omitted":0,"hint":[]},
  {"kind":"code","items":[{"repo":null,"path":"src/client.py","line":2,"symbol":"def request():","layer":"api","via":"core::docs/api.md#request"}],"omitted":0,"hint":[]}],
 "checks":{"staleness":{"state":"full","checked":0,"total":0,"scope":"local"},"repos":[
  {"repo":null,"state":"ok","head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","dirty":false,"reason":null,"read":["docs","decisions","code","tests"]},
  {"repo":"core","state":"ok","head":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","dirty":false,"reason":null,"read":["docs"]}]},
 "reproducible":true,"incomplete":false,
 "notes":[
  {"code":"repos-scope","text":"Available repositories: local, core."},
  {"code":"cross-repo-staleness","text":"cross-repository staleness was not checked"}]}
```

**Грязный сосед.** При незакоммиченной правке, не меняющей связей, блоки и
счётчики те же. В метаданных `core` — `dirty: true`; на верхнем уровне
`reproducible: false`, `incomplete: false`. В тексте рядом с HEAD написано
«грязное дерево», в `notes` добавляется такой элемент:

```json
{"code":"repos-unreproducible","text":"core: dirty worktree. The response is not reproducible."}
```

**Недоступный сосед при `"T4": "off"`.** Тот же запрос даёт код 0.
Текст называет цель без заголовка и пометки о её нахождении, затем:

```text
источники: свой aaaaaaa, чистый; core недоступен
Доступные источники: свой.
core недоступен: каталог подключения не найден; связи не проверены
межрепозиторное устаревание не проверено
```

Нет сигнала T4, но неполнота остаётся. Это полный JSON ответа:

```json
{"schema":1,
 "target":{"repo":"core","kind":"section","target":"docs/api.md#request","title":""},
 "summary":{"errors":0,"warnings":0,"decisions":0,"rules":0,"concepts":0,"entry":0,"code":0,"layers":0,"tests":0,"open_work":0,"targets":0,"repos":0},
 "blocks":[],
 "checks":{"staleness":{"state":"full","checked":0,"total":0,"scope":"local"},"repos":[
  {"repo":null,"state":"ok","head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","dirty":false,"reason":null,"read":["docs","decisions","code","tests"]},
  {"repo":"core","state":"unavailable","head":null,"dirty":null,"reason":"connected repository directory not found","read":["docs"]}]},
 "reproducible":false,"incomplete":true,
 "notes":[
  {"code":"repos-scope","text":"Available repositories: local."},
  {"code":"repos-incomplete","text":"core is unavailable: connected repository directory not found. Links unchecked"},
  {"code":"cross-repo-staleness","text":"cross-repository staleness was not checked"}]}
```
