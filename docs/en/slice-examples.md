# Slice examples

See the [slice contract](slice.md) for target forms, block contents, the output budget, and the JSON schema.

**Section.** `lipi slice docs/pricing.md#threshold`

Here the anchor is in a paragraph. Its title comes from the paragraph text. When the title exceeds 80 characters, lipi shortens it at a word boundary and appends an ellipsis.

```text
docs/pricing.md#threshold — A 5% discount applies to orders of at least $100 excluding shipping. Compare…
1 warning · 1 decision · 1 rule · 2 entry points · 5 code locations (3 layers) · 2 tests · 1 open work item
checked 7 of 7 locations for staleness

Signals
  ! A4  src/domain/discount.py:12 — code changed on 2026-11-12 09:14:00 UTC, after the section (2026-10-03 18:40:00 UTC)
  · ISS-007 open — The threshold ignores refunds (links to the section)
Rules and decisions to follow
  ADR-018 accepted — Discounts use the total before shipping (link)
  .agents/architecture.md#money — Monetary amounts use Money (mark)
Excerpt
  A 5% discount applies to orders of at least $100 excluding shipping. Compare the rounded
  total with the threshold. See [Rounding](#rounding).
Entry points
  src/api/orders.py:88  def post_order(request):  [api]
  src/app/checkout.py:40  def apply_discount(order):  [app]
Code locations
  src/app/settings.py:21  DISCOUNT_THRESHOLD = Money(10_000)  [app]
  src/domain/discount.py:12  class DiscountPolicy:  [domain]
  src/domain/discount.py:57  def threshold_for(customer):  [domain]
Tests
  tests/test_checkout.py:30  def test_discount_applied():
  tests/test_discount.py:8  def test_threshold_boundary():
Context
  docs/orders.md#total — Order total
  docs/pricing.md#rounding — Rounding
```

The same items in JSON (`--format json`):

```json
{
 "schema": 1,
 "target": {"target": "docs/pricing.md#threshold", "title": "A 5% discount applies to orders of at least $100 excluding shipping. Compare…", "kind": "section", "found": "exact"},
 "summary": {"errors": 0, "warnings": 1, "decisions": 1, "rules": 1, "concepts": 0, "entry": 2, "code": 5, "layers": 3, "tests": 2, "open_work": 1, "targets": 0},
 "blocks": [
  {"kind": "signals", "omitted": 0, "hint": [], "items": [
   {"code": "A4", "level": "warning", "message": "code changed on 2026-11-12 09:14:00 UTC, after the section (2026-10-03 18:40:00 UTC)", "target": "docs/pricing.md#threshold", "path": "src/domain/discount.py", "line": 12},
   {"code": null, "level": "info", "message": "ISS-007 open — The threshold ignores refunds (links to the section)", "target": "ISS-007"}
  ]},
  {"kind": "obey", "omitted": 0, "hint": [], "items": [
   {"target": "ADR-018", "title": "Discounts use the total before shipping", "relation": "link", "status": "accepted"},
   {"target": ".agents/architecture.md#money", "title": "Monetary amounts use Money", "relation": "mark"}
  ]},
  {"kind": "excerpt", "omitted": 0, "hint": [], "items": [
   {"text": "A 5% discount applies to orders of at least $100 excluding shipping. Compare the rounded\ntotal with the threshold. See [Rounding](#rounding).", "lines": 2, "cut": false}
  ]},
  {"kind": "entry", "omitted": 0, "hint": [], "items": [
   {"path": "src/api/orders.py", "line": 88, "symbol": "def post_order(request):", "layer": "api", "via": "docs/pricing.md#threshold"},
   {"path": "src/app/checkout.py", "line": 40, "symbol": "def apply_discount(order):", "layer": "app", "via": "docs/pricing.md#threshold"}
  ]},
  {"kind": "code", "omitted": 0, "hint": [], "items": [
   {"path": "src/app/settings.py", "line": 21, "symbol": "DISCOUNT_THRESHOLD = Money(10_000)", "layer": "app", "via": "docs/pricing.md#threshold"},
   {"path": "src/domain/discount.py", "line": 12, "symbol": "class DiscountPolicy:", "layer": "domain", "via": "docs/pricing.md#threshold"},
   {"path": "src/domain/discount.py", "line": 57, "symbol": "def threshold_for(customer):", "layer": "domain", "via": "docs/pricing.md#threshold"}
  ]},
  {"kind": "tests", "omitted": 0, "hint": [], "items": [
   {"path": "tests/test_checkout.py", "line": 30, "symbol": "def test_discount_applied():", "layer": "tests"},
   {"path": "tests/test_discount.py", "line": 8, "symbol": "def test_threshold_boundary():", "layer": "tests"}
  ]},
  {"kind": "context", "omitted": 0, "hint": [], "items": [
   {"target": "docs/orders.md#total", "title": "Order total", "relation": "link", "depth": 1},
   {"target": "docs/pricing.md#rounding", "title": "Rounding", "relation": "link", "depth": 1}
  ]}
 ],
 "incomplete": false,
 "notes": [
  {"code": "staleness-full", "text": "checked 7 of 7 locations for staleness"}
 ],
 "checks": {
  "staleness": {"state": "full", "checked": 7, "total": 7}
 }
}
```

**Code file.** `lipi slice src/domain/discount.py`. The staleness coverage line
is omitted from this example.

```text
src/domain/discount.py — code file [domain]
1 warning · 1 decision · 1 rule · 3 concepts · 4 code locations (2 layers) · 3 tests · 1 open work item
no trace markers in layers domain

Signals
  ! T3  src/domain/discount.py:69 — ISS-004 closed — check whether the link is needed. Remove it if it was a temporary workaround.
  · ISS-007 open — The threshold ignores refunds (links to the target)
Rules and decisions to follow
  ADR-018 accepted — Discounts use the total before shipping (link)
  .agents/architecture.md#money — Monetary amounts use Money (mark)
Concepts
  .agents/architecture.md#money — Monetary amounts use Money (1 code location)
  docs/pricing.md#rounding — Rounding (2 code locations)
  docs/pricing.md#threshold — A 5% discount applies to orders of at least $100 excluding shipping. Compare… (5 code locations)
Tests
  tests/test_checkout.py:30  def test_discount_applied():
  tests/test_discount.py:8  def test_threshold_boundary():
  tests/test_rounding.py:31  def test_rounding_half_up():
Code locations
  src/api/orders.py:88  def post_order(request):  [api]
  src/app/checkout.py:40  def apply_discount(order):  [app]
  src/app/rounding.py:9  def round_total(amount):  [app]
  src/app/settings.py:21  DISCOUNT_THRESHOLD = Money(10_000)  [app]
Context
  docs/orders.md#total — Order total
```

**Work item.** `lipi slice ISS-007`

```text
ISS-007 — The threshold ignores refunds (open)
1 decision · 1 rule · 2 code locations (1 layer) · 1 target
no trace markers in layers api, app, tests

Rules and decisions to follow
  ADR-018 accepted — Discounts use the total before shipping (link) — via docs/pricing.md#threshold
  .agents/architecture.md#money — Monetary amounts use Money (mark) — via docs/pricing.md#threshold
Code locations
  src/domain/discount.py:65  def net_total(order):  [domain]
  src/domain/refunds.py:15  class RefundLedger:  [domain]
Work item targets
  docs/pricing.md#threshold — A 5% discount applies to orders of at least $100 excluding shipping. Compare… (5 code locations)
```

When several linked targets share an applicable decision, the decision appears once, with all the targets listed under `via`:

```json
{"target": "ADR-018", "title": "Discounts use the total before shipping", "relation": "link", "status": "accepted", "via": ["docs/pricing.md#rounding", "docs/pricing.md#threshold"]}
```

## Code changes <a id="diff"></a>

In this `lipi slice --staged` example, one declaration marked with `docs/pricing.md#threshold` and one unmarked region changed. Inspect the other locations and tests to decide whether they also need an edit. A4 is disabled for this example.

```text
--staged — check related locations
1 decision · 1 concept · 1 code location (1 layer) · 1 test
check related locations, decisions, and tests
changes without trace markers: 1 location

Rules and decisions to follow
  ADR-018 accepted — Discounts use the total before shipping (link)
Concepts
  docs/pricing.md#threshold — Discount threshold (2 code locations)
Code locations
  src/api/orders.py:88  def post_order(request):  [api]
Tests
  tests/test_discount.py:8  def test_threshold_boundary():
```

In JSON, the target has `kind: "diff"` and `target: "--staged"`. The diff details are `{"mode": "staged", "base": null, "files": 1, "unmarked": 1}`. The [diff contract](slice-diff.md) uses the ordinary selection rules and budget.

**Empty slice.** `lipi slice docs/pricing.md#refunds` returns 0:

```text
docs/pricing.md#refunds — Refunds
no trace markers. Search the code
no trace markers in layers api, app, domain, tests
```

In JSON, `blocks` is empty and `notes` contains a note with code `no-marks`.

**Truncation.** The code locations block from `lipi slice docs/orders.md#total` on a target with 47 code locations:

```text
Code locations
  src/domain/order.py:20  class Order:  [domain]
  …
  showing 12 of 47. Show more with --only code, --layer
```

In JSON, the block carries `"omitted": 35` and `"hint": ["--only code", "--layer"]`. The response has `"incomplete": true`.

**Ambiguous target.** `lipi slice discount` returns 1:

```text
target "discount" is ambiguous; candidates:
  ADR-018 — Discounts use the total before shipping
  docs/loyalty.md#tier-threshold — Discount by tier
  docs/pricing.md#threshold — A 5% discount applies to orders of at least $100 excluding shipping. Compare…
```

The JSON response lists the same candidates.

```json
{
 "schema": 1,
 "error": "ambiguous",
 "query": "discount",
 "candidates": [{"target": "ADR-018", "title": "Discounts use the total before shipping"}, {"target": "docs/loyalty.md#tier-threshold", "title": "Discount by tier"}, {"target": "docs/pricing.md#threshold", "title": "A 5% discount applies to orders of at least $100 excluding shipping. Compare…"}]
}
```

A query with no matches also exits with 1.

```json
{"schema": 1, "error": "not-found", "query": "unmatched-needle", "candidates": []}
```

## Connected repositories <a id="repos"></a>

These examples illustrate the [repository connection contract](slice.md#repos). The SHAs come from the example repositories. Both repositories have clean working trees. Local code references an external section, and there are no other links. `lipi slice core::docs/api.md#request` returns 0:

```text
core::docs/api.md#request — Request
1 code location (1 layer, 1 repository)
sources: local bee9e29, clean; core 3c5db3b, clean
Available repositories: local, core.
cross-repository staleness was not checked

Excerpt
  ## Request

  A request includes an ID.
Code locations
  src/client.py:2  def request():  [api]
```

Full JSON for the same response:

```json
{
 "schema": 1,
 "target": {"target": "docs/api.md#request", "title": "Request", "kind": "section", "repo": "core", "found": "exact"},
 "summary": {"errors": 0, "warnings": 0, "decisions": 0, "rules": 0, "concepts": 0, "entry": 0, "code": 1, "layers": 1, "tests": 0, "open_work": 0, "targets": 0, "repos": 1},
 "blocks": [
  {"kind": "excerpt", "omitted": 0, "hint": [], "items": [
   {"text": "## Request \n\nA request includes an ID.", "lines": 3, "cut": false}
  ]},
  {"kind": "code", "omitted": 0, "hint": [], "items": [
   {"path": "src/client.py", "line": 2, "symbol": "def request():", "layer": "api", "repo": null, "via": "core::docs/api.md#request"}
  ]}
 ],
 "incomplete": false,
 "notes": [
  {"code": "repos-scope", "text": "Available repositories: local, core."},
  {"code": "cross-repo-staleness", "text": "cross-repository staleness was not checked"}
 ],
 "checks": {
  "staleness": {"state": "full", "checked": 0, "total": 0, "scope": "local"},
  "repos": [
   {"repo": null, "state": "ok", "head": "bee9e296734a0abd4d4b9dae8d3116da22914f57", "dirty": false, "reason": null, "read": ["docs", "decisions", "code", "tests"]},
   {"repo": "core", "state": "ok", "head": "3c5db3bed1abde455866afadf4f0d7465b165288", "dirty": false, "reason": null, "read": ["docs"]}
  ]
 },
 "reproducible": true
}
```

**Dirty working tree.** If the connected repository has an uncommitted edit that does not change the links, the blocks and counts stay the same. The metadata for `core` has `dirty: true`. The top-level flags are `reproducible: false`, `incomplete: false`. The text output indicates the dirty working tree next to HEAD, and the following note appears:

```json
{"code": "repos-unreproducible", "text": "core: dirty worktree. The response is not reproducible."}
```

**Unavailable repository with `"T4": "off"`.** The query still returns 0. The text shows the requested address and the source state.

```text
core::docs/api.md#request
sources: local 1e436ff, clean; core unavailable
Available repositories: local.
core is unavailable: connected repository directory not found. Links unchecked
cross-repository staleness was not checked
```

The T4 signal is hidden and the response still reports incomplete coverage. Full JSON:

```json
{
 "schema": 1,
 "target": {"target": "docs/api.md#request", "repo": "core", "title": "", "kind": "section"},
 "summary": {"errors": 0, "warnings": 0, "decisions": 0, "rules": 0, "concepts": 0, "entry": 0, "code": 0, "layers": 0, "tests": 0, "open_work": 0, "targets": 0, "repos": 0},
 "blocks": [],
 "incomplete": true,
 "notes": [
  {"code": "repos-scope", "text": "Available repositories: local."},
  {"code": "repos-incomplete", "text": "core is unavailable: connected repository directory not found. Links unchecked"},
  {"code": "cross-repo-staleness", "text": "cross-repository staleness was not checked"}
 ],
 "checks": {
  "staleness": {"state": "full", "checked": 0, "total": 0, "scope": "local"},
  "repos": [
   {"repo": null, "state": "ok", "head": "1e436fffcf7dc13f5de0a818c84a2a60b2a04b3b", "dirty": false, "reason": null, "read": ["docs", "decisions", "code", "tests"]},
   {"repo": "core", "state": "unavailable", "head": null, "dirty": null, "reason": "connected repository directory not found", "read": ["docs"]}
  ]
 },
 "reproducible": false
}
```
