# Project trace map

`lipi map` shows where project knowledge is linked to code and tests. Rows are targets, columns are code layers and tests, and cells count locations. A zero means that lipi found no trace markers for that cell. To investigate a row, open its [slice](slice.md), for example `lipi slice docs/rules.md#limit`.

```bash
lipi map
lipi map --format json
lipi help map
```

## Which rows appear <a id="rows"></a>

The map includes documentation in all language editions, decisions, the root README, `AGENTS.md`, and the project's own files in `.agents/`. Unmarked pages in these categories show which knowledge has yet to be linked to code. Plans, issues, discussions, audits, and other Markdown files appear only when a marker targets the document or one of its anchors. Work items and decisions show the status from their headers, including on anchor rows. An unmarked workflow index or master plan does not appear. [Connection rules](#repos) govern external rows.

- An ordinary page without markers has one row for its path.
- When a code or test marker targets a page anchor, the map shows every unambiguous explicit anchor on that page, including anchors with zero locations. There is no separate page row: markers for ordinary pages require an anchor.
- A decision has a row for its ID (for example `ADR-001`). This row counts only markers that target the ID. If a marker targets the ID or an anchor, rows for all the decision's anchors follow; otherwise only the ID row appears. Marked work items follow the same rule.
- Decisions sharing an ID appear separately by path. A marker pointing to the ambiguous ID contributes no count.
- Ordinary links, `covers`, and `Refines` neither expand pages nor add locations. The map counts direct code and test markers.

Decision groups are ordered by ID, other pages by path. Within a group the ID row, when present, comes first, followed by anchors in file order. Target and code-scan exclusions match those of slices: `skip_dirs`, `.agents/lipi/`, archives (`history/`, `<workflow>/history/`, `<decisions>/history/`), and Git-ignored files. The map also works outside Git.

## Counting locations <a id="counts"></a>

A location is a group of adjacent marker-only lines before a declaration, or one code line with an inline marker. Its identity includes repository, path, and line. Repeating a target in a group counts once for that target. Adjacent code lines with inline markers count separately. A group with several targets contributes once to each. Summing rows can therefore count a single location more than once.

Configure layers and tests with [`layers` and `tests`](settings.md#layers). Configured code layers appear in configuration order even when their counts are zero. Additional layers appear alphabetically. The default layer is the top-level directory, or `.` for a file at the root. Test locations count exclusively in the tests column; a layer named `tests` also identifies tests.

Only resolved markers count. The command requires no checker run, audit, project-defined `checks`, history walk, or `git blame`. It leaves the index, baseline, and other project files untouched. Run `lipi check` for marker errors, and use `lipi slice` or `lipi audit` for staleness and target status.

## Text and JSON <a id="output"></a>

Text headings and labels follow the interface language. In JSON, lipi writes `note` and `notes[].text` in English and keeps titles as written in the project.

Text and JSON contain the same rows and counts. The slice output budget does not apply. Text shows target, title, status, code layers, and tests with all zeros visible. An unmarked page or ID row may have marked anchors below it. A zero page or ID row is marked `no trace markers`, and an empty map says `no matching targets`. The output explains the meaning of zero even when there are no eligible targets. [Connected repositories](#repos) add source columns and scope information. Unread data is excluded from counts.

| Field | Value |
| --- | --- |
| `schema` | `1` |
| `layers` | Ordered code columns, excluding tests |
| `rows` | Rows in display order |
| `note` | Explanation of what zero means |

A row has `target`, `title`, `kind` (`page`, `section`, `decision`, or `work`), `code` (a layer-to-count object with every column, including zeros), and a numeric `tests` count. Only decisions, work items, and their anchors carry `status`. A target is a path, a path with an anchor, or a canonical work item ID. For a concept in a project with `api` and `domain` layers:

```json
{
 "target": "docs/rules.md#limit",
 "title": "Limit",
 "kind": "section",
 "code": {"api": 1, "domain": 0},
 "tests": 2
}
```

## Exit codes <a id="exit"></a>

- **0**: a map was produced. This includes empty maps and incomplete maps even if T4 has severity `error`.
- **2**: invalid arguments or settings. Invalid settings raise C1. With `--format json` the output uses the checker's findings format.

The map does not search for an individual target and has no exit code 1.

## Connected repositories <a id="repos"></a>

A nonempty `repos` adds sources. Without connections the ordinary schema and behavior apply.

### Rows and scope

External rows are included only for targets directly marked by **local** code or tests. A readable external page expands according to the [usual row rules](#rows), including file-order anchors and an ID row for decisions. Reading requires `docs` or `decisions` according to target type. If the connected repository has no `lipi.json`, only the explicit anchors on a readable page are available. It contributes no ID or page target and cannot be searched for consumers. Rows are identified by `(repo, target)`. Local groups come first, then external groups in `repos` key order. Normal ordering applies within each source. Markdown links and `covers` add neither rows nor locations.

Reverse lookup searches direct connections with `read: code` or `tests`. It adds locations only when the repository name in an external marker resolves to the **local** project root. The two ends may use different names for the connection. Lookup stops at the direct neighbor. Its local markers and markers targeting third repositories do not expand the map. Its agent instructions are not imported.

`code` grants access to ordinary code locations, `tests` to test locations. With only `code`, external tests do not count. With only `tests`, the neighbor contributes no ordinary code layers. Its settings determine classification, layers, and exclusions. The text and the `repos-scope` note identify the declared, readable sources covered by the counts.

### Columns and JSON

The schema stays at 1. The existing `note` and counters keep their meaning. A nonempty `repos` adds these fields:

| Field | Value |
| --- | --- |
| `checks.repos`, `reproducible` | [Source metadata](slice.md#repos) for the local repository and all declared connections |
| `incomplete` | True if at least one connected repository is unavailable |
| `notes` | Objects with `code` and `text` reporting scope, availability, and reasons a result cannot be reproduced |
| `signals` | T4 signals for unavailable connections |
| `rows[].repo` | `null` for a local target, otherwise the name of the target's repository |
| `rows[].test_counts` | Ordered `{repo, count}` objects for each readable source of tests, including zeros |

`rows[].target` has no repository prefix. Column names in `layers` start with the local layers, then `<name>::<layer>` for neighbors with `read: code`, in connection order. Each `rows[].code` includes every column, including zeros. Layers within a source retain their ordinary order. A layer name containing `::` with connections enabled raises C1. Without `repos`, the ordinary rules for layer names apply.

`rows[].tests` equals the sum of `test_counts[].count`. Tests do not add entries to `code`. In `test_counts`, the local source comes first, followed by available connections with `tests` access.

Text output groups local layers and tests first, then each connection's layers and, if permitted, its tests column. The columns also appear when there are no rows. Text prefixes an external target with `<name>::`. Zeros appear only for readable sources. An unavailable source contributes no columns or `test_counts` entries. If reading fails partway through a source, its rows and locations are discarded and counts recomputed. Local data stays intact. Results are independent of file read order.

In the following complete response, a local concept has one location in the `api` layer and one local test. The `client` connection permits `["code", "tests"]` and contributes two `ui` locations and two tests:

```json
{
 "schema": 1,
 "layers": ["api", "client::ui"],
 "rows": [
  {"repo": null, "target": "docs/rules.md#limit", "title": "Limit", "kind": "section", "code": {"api": 1, "client::ui": 2}, "tests": 3, "test_counts": [{"repo": null, "count": 1}, {"repo": "client", "count": 2}]}
 ],
 "note": "0 means no links were found. An implementation may still exist.",
 "checks": {
  "repos": [
   {"repo": null, "state": "ok", "head": "3e321041ffb99a7f5a5643f57649364879d435e6", "dirty": false, "reason": null, "read": ["docs", "decisions", "code", "tests"]},
   {"repo": "client", "state": "ok", "head": "b26efd399cc656aa3b5e47ef4f8c8a77c25fdeb9", "dirty": false, "reason": null, "read": ["code", "tests"]}
  ]
 },
 "reproducible": true,
 "incomplete": false,
 "notes": [
  {"code": "repos-scope", "text": "Available repositories: local, client."}
 ],
 "signals": []
}
```

### Availability and reproducibility

The map reads metadata from the local repository and every direct connection, including repositories that contribute no rows or columns. It reads HEAD and working-tree status, without walking history or running blame. JSON contains full SHAs; text displays their first seven characters. `reproducible` is true only if every source has `state: "ok"`, a known HEAD, and `dirty: false`. A dirty tree, missing Git, or missing HEAD makes the result unreproducible. Readable data still participates and these conditions alone do not set `incomplete`. The text and the `repos-unreproducible` note explain why.

An unavailable source sets `incomplete: true` and `reproducible: false`, adds a `repos-incomplete` note, and raises T4. Its signal has `repo`, `target_repo`, and `target` set to the connection name, together with `code: "T4"`, `level`, and `message`. Local `codes` settings determine severity. With `off`, metadata, coverage, and notes still report the unavailable source. In `lipi check`, T4 at `error` returns 1.

For the previous example, if `client` is unavailable and `"T4": "off"`, the following **JSON fragment** replaces the corresponding fields:

```json
{
 "layers": ["api"],
 "rows": [
  {"repo": null, "target": "docs/rules.md#limit", "title": "Limit", "kind": "section", "code": {"api": 1}, "tests": 1, "test_counts": [{"repo": null, "count": 1}]}
 ],
 "incomplete": true,
 "reproducible": false,
 "signals": [],
 "notes": [
  {"code": "repos-scope", "text": "Available repositories: local."},
  {"code": "repos-incomplete", "text": "client is unavailable: connected repository directory not found. Links unchecked"}
 ],
 "checks": {
  "repos": [
   {"repo": null, "state": "ok", "head": "ee7b1609b482006dcad81c9998fcca6755d93c31", "dirty": false, "reason": null, "read": ["docs", "decisions", "code", "tests"]},
   {"repo": "client", "state": "unavailable", "head": null, "dirty": null, "reason": "connected repository directory not found", "read": ["code", "tests"]}
  ]
 }
}
```

The command returns **0** for any map it can produce, even if incomplete or carrying T4 at `error`. Invalid arguments or local settings return **2**. Invalid settings in a connected repository make that source unavailable. Counts describe only data that was read. The map does not compute external staleness.
