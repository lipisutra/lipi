# Slice with `lipi slice`

A slice gathers what you need to know before working on a target or reviewing
code changes. It orders the results, limits their size, and reports gaps in
coverage. Text is for people and JSON is the contract for tools and agents.

```bash
lipi slice <target> [--format json] [--full] [--depth 2|3]
                   [--layer <layer>]... [--only <block>[,<block>]]
lipi slice --diff <base> | --staged
```

A slice is read-only. It leaves files, including `INDEX.md` and the baseline,
untouched and runs no project checks. The `codes` levels apply. Disabled codes
are omitted from the signals and summary. See [diff slices](slice-diff.md) for
modes that read changes and their JSON. The output flags apply to both kinds
of slice.

## Target <a id="target"></a>

| Input | Target |
| --- | --- |
| `docs/pricing.md#threshold` | Section, with a project-relative path |
| `docs/pricing.md` | Page |
| `ADR-018` | Decision. Case and leading zeroes are ignored, as in `adr-18`. |
| `ISS-007`, `PLN-005`, `DSC-002`, `AUD-001` | Work item |
| `src/domain/discount.py` | Existing file other than `.md`, subject to [exclusions](map.md#rows) and Git filtering |
| Text, such as a word or quoted phrase, without a path, `.md`, anchor, or ID form | Search query |

Search tries an exact anchor or ID, then a substring of anchors and IDs, then
a substring of titles. A single match produces a slice and the target line
shows how it was found. Zero or multiple matches exit with 1 and list up to
five candidates in a fixed order. Anchor and ID matches come before title
matches. Within each group, results sort by `target`, with alphabetical paths
and IDs ordered by type and number. If nothing is similar, the candidate list
is empty.

A page target with no anchor in the query returns page signals and a
`concepts` block with the page's anchors and the code location count for each.

A concept's title comes from the heading text, the first cell of a table row,
or the beginning of a paragraph or list item's own text, depending on the
anchor's placement. The anchor and markup are removed and whitespace is
collapsed. Paragraph and item titles are limited to 80 characters at a word
boundary, including a final `…` if truncated. A single word that exceeds the
limit is cut within the word and followed by `…`.

## Exit codes <a id="exit"></a>

- **0** means the slice was returned, including an empty or incomplete
  one. Signal levels do not affect the exit code.
- **1** means the target was missing or ambiguous. The response lists
  candidates.
- **2** means invalid arguments, C1 settings or state errors, or a
  Git diff error.

## Blocks <a id="blocks"></a>

Text headings follow the interface language. In JSON, lipi writes its explanations in `message` and `notes[].text` in English, preserving project text.

| `kind` | Text heading | Contents |
| --- | --- | --- |
| `signals` | Signals | Staleness (A4), target or `@trace` and `covers` status (T3), open work items, and connected repository issues (T4) |
| `obey` | Rules and decisions to follow | Accepted decisions and sections from `AGENTS.md` or `.agents/`, excluding `.agents/lipi/` |
| `excerpt` | Concept | The selected portion of the target |
| `concepts` | Concepts | Sections implemented by a code file or anchors in a page |
| `entry` | Entry points | Code locations that match `entry` |
| `code` | Code locations | Other code locations by layer |
| `tests` | Tests | Test locations |
| `targets` | Work item targets | Targets linked from a work item |
| `context` | Context | Titles of neighboring documents |

Signals appear first. If the target itself is a `superseded` or `rejected`
decision, a `closed` issue or discussion, or a `completed` or `canceled` plan,
the first signal is T3 for its status. It includes the successor for a
superseded decision when available. For a final target, its message says the
slice covers the historical work item. Messages for trace and `covers` links
identify what to review where code relies on those targets. `codes` sets the
severity. Ordinary links from documentation or agent instructions to
superseded or rejected decisions also raise T3 and prompt a review of the
text. Decisions from `decisions` are available with `"workflow": null`. Other
blocks depend on the target.

| Target | Order after signals |
| --- | --- |
| Section or decision | `obey`, `excerpt`, `entry`, `code`, `tests`, `context` |
| Page | `obey`, `concepts`, `entry`, `code`, `tests`, `context` |
| Code file | `obey`, `concepts`, `tests`, `code` (other locations for the same concepts), `context` |
| Work item | `obey`, `code` (trace markers for its ID), `targets`, `context` |
| Diff | `obey`, `concepts`, `entry`, `code`, `tests`, `context` |

- **Applicable rules and decisions.** The `obey` block uses two
  `relation` values. `link` means a document links to the target.
  `mark` means the document and target are named in the same trace
  marker group before one declaration. Superseded and rejected
  decisions appear as signals.
- **Work items.** The `obey` block also follows each direct link from the
  item and applies the same related-document and refinement rules.
  Each supporting document has `via` containing the targets through
  which it was found. A direct link to the work item uses its ID.
  The block shows each supporting document once with its title and
  all `via` paths. It skips the linked targets' own slices. A directly
  linked decision includes its supporting and refining decisions as
  in a slice of that decision itself.
- **Decision refinements.** Only a header line of the form
  `- Refines: [ADR-NNN](path.md)` defines this relation. It may repeat.
  For a decision ID, `obey` includes the accepted target, its
  accepted base decisions (the ones it refines) up the chain, and its
  accepted refinements down the chain. Walking up the chain does not
  branch into other refinements of a base decision. For a section or code file, the
  block includes the related decision and its refinements downward.
  Ordinary links between decisions provide context. A branch stops
  at a decision that is not accepted. `proposed` produces an info
  signal and `superseded` or `rejected` produces T3. Cycles visit
  each node once. Refinement uses `relation: link` and is evaluated
  before truncation.
- **Open work at this location.** An item that links to the target or
  appears in the same trace marker group is open work when it is an
  `open` or `in progress` issue, a `new`, `in progress`, or
  `pending acceptance` plan, an `open` discussion, or a `proposed`
  decision. A proposed decision could change the rules for the
  location. Deferred plans, accepted decisions, and audits are
  excluded. The signal has level `info` and `code: null`.
- **Code locations.** Each location has a file, trace marker line,
  and declaration. The declaration is the first nonblank,
  noncomment line after the group, before the next group or EOF.
  Lines starting after indentation with `#`, `//`, `/*`, `*`, `--`,
  `;`, or `<!--` are skipped. No declaration produces an empty
  name. An inline trace marker uses its own code line. Names are
  limited to 80 characters. `layers` chooses the layer, with the
  top-level directory as the default.
- **Tests.** A test location is in a file in the `tests` layer or
  matched by the filename patterns in [settings](settings.md).
- **Concepts.** For a code file, concepts are the sections its trace
  markers target. For a page, they are its anchors. Each has a
  project-wide count of code locations.
- **Shared code.** Sharing a code file does not create neighbors.
  A file implementing several concepts lists them within the
  output budget and reports the number omitted.
- **Depth.** At depth 1, neighbors are documents with an explicit
  link to or from the target. A work item includes documents
  that link to it. A section uses links to and from that section
  specifically. Page links belong to the page target. `--depth 2|3`
  adds titles of neighbors of neighbors. The
  [workflow indexes](workflow.md#files) and `<workflow>/masterplan.md`,
  including their anchors, are excluded from this walk. They can
  still be queried directly.

**Order within blocks.** Signals start with the target's own T3, then sort by
`error`, `warning`, and `info`, then path and line. Code locations sort by
`layers` order or alphabetically without settings, then path and line.
Documents show decisions by ID first, then paths alphabetically.

## Summary <a id="summary"></a>

The first line after the target is the summary. It omits zero counts and lists
the remaining counts in this order: errors, warnings, decisions, rules,
concepts, entry points, code locations and layers, tests, open work items, and
work item targets.

```text
1 warning · 1 decision · 1 rule · 2 entry points · 5 code locations (3 layers) · 2 tests · 1 open work item
```

JSON retains zeros. Keys are `errors`, `warnings`, `decisions`, `rules`,
`concepts`, `entry`, `code`, `layers`, `tests`, `open_work`, and `targets`.
With connections, `repos` counts repositories with nontest locations and
`layers` counts distinct repository and layer pairs.

`decisions` and `rules` count each supporting document in `obey` once,
including documents found through several work item targets. Code locations
include entry points and exclude tests. The summary counts the full slice
before truncation, and counts A4 only where confirmed by the check. Staleness
coverage is shown separately and is independent of truncation.

## Staleness checks <a id="staleness"></a>

A4 filters by history, then runs blame without `-C` for up to 64 files and
with `-C` for up to 16. Only verified staleness raises a signal. Uncommitted
edits share a timestamp. `checks.staleness` reports `state`, `checked`, and
`total`. Audit covers all files. See [staleness boundaries and
order](slice-output.md#staleness) and [A4 reviews](review.md#summary).

## Output budget <a id="budget"></a>

Text and JSON use the same line budget. Up to the first half goes to severe
signals, then each block gets up to three lines. Remaining lines are assigned
in output order. An excerpt uses up to one third of the budget. `--full`
includes it outside the budget. The summary is computed before truncation, and
`--only` preserves signals. See [content selection](slice-output.md#budget)
for details.

## Empty slices <a id="empty"></a>

Missing trace markers, Git, or locations in some layers are reported in
`notes`. See [empty slice notes](slice-output.md#empty).

## JSON <a id="json"></a>

`schema: 1` uses the [response schema](slice-output.md#json). When
`reviews.json` exists, the summary includes
[`reviewed_pairs`](review.md#summary). New keys are compatible. Removing a key
or changing its meaning requires a new schema and major version.

## Examples <a id="examples"></a>

See [slice examples](slice-examples.md) for full text and JSON responses,
empty slices, truncation, and search.

## Connected repositories <a id="repos"></a>

Connection fields appear only with `repos`. They use the same metadata as the
[map](map.md#repos). The reviewed pair count is local.

### Targets and links

- Queries and searches without a prefix are local. For external
  targets, use `core::docs/api.md#request`, `core::docs/api.md`, or
  `core::ADR-018`. `core::request` searches allowed targets. A neighbor
  without `lipi.json` supports only an exact `path#anchor`, with no
  search or backlinks. External code files, work items other than
  decisions, and agent instructions are unsupported.
- An unknown connection or missing or disallowed target exits with
  1 and returns `error: not-found` with the reason in `message`.
  Ambiguity uses `ambiguous`. Refusals for a work item ID or search
  also give a reason. Candidates have `repo`. An invalid invocation
  or local C1 exits with 2.
- A known but unavailable connection exits with 0 and returns
  `incomplete: true`. `target` preserves `repo` and the prefix-free
  query. `title` is empty and `found` is omitted. The query form
  determines `kind`, which is `null` for search. Existence is unknown.
- An external target gets its excerpt and context from allowed
  scopes in its own repository. The code and tests come from the
  local project. For a local concept, backlinks add locations from
  connected repositories. `code` allows code and `tests` allows test
  files according to each neighbor's settings. A reference back to
  the local project is recognized by its physical root, regardless
  of name. Third repositories, external work items, and external
  instructions are excluded even from context.
- `obey` preserves local rules. An accepted external decision enters
  through a direct local code marker on its ID, together with
  accepted refinements from that same source under the usual
  decision rule. Reading requires `decisions`. Third repositories
  are excluded. The direct-marker requirement applies to `obey`.
- A local code file slice follows external trace markers.
  `--diff` and `--staged` read changes only from the local tree, with
  external targets and backlinks as described above.

### Addresses, order, and counts

Targets, candidates, and addressable items have `repo`, set to `null` for the
local project or the connected repository name. `path` and `target` omit the
prefix. Identity is `(repo, target)` or `(repo, path, line)`. For signals,
`repo` identifies the owner of `path`, or the target's owner without `path`. A
separate, required `target_repo` identifies the target's owner. A local T3 on
an external decision could look like this:
`{"repo":null,"path":"src/client.py","line":2,"target_repo":"core","target":"ADR-018"}`.
Text output uses qualified addresses such as `core::ADR-018`. `via` keeps its
type and canonical markers, including prefixes as seen from the current
project.

Blocks retain their usual order. Within a block, local items come first, then
connected repositories in `repos` order, followed by the usual layer, path,
and ID order. Signals show target T3 first, then sort by severity, source,
path, and line. An item's `layer` omits the prefix. `--layer` selects a local
layer name or a qualified `<connection>::<layer>`. With connections enabled,
`::` in a layer name raises C1. A single budget applies to all sources. The
summary and `code_count` count locations in available sources. `--only`
preserves source information.

### Source state and incomplete results

`checks.repos` lists the local source, then all connections in settings order.
Each object contains `repo`, `state` (`ok`, `unavailable`, or `no-git`),
`head` (repository SHA or `null`), `dirty` (staged, unstaged, or nonignored
untracked repository changes, or `null` if unknown), `reason` (why the source
is unavailable or lacks Git, otherwise `null`), and the configured `read`
array. The local source has `repo: null` and `read` lists `docs`, `decisions`,
`code`, and `tests`, without changing local permissions. The metadata for
every connection is read once even if its code is unnecessary. A `no-git`
source can be read. Before the first commit, a source may have `state: ok`,
`head: null`, and known `dirty`.

An unreadable target makes the source `unavailable` with `head` and `dirty`
set to `null`. The response drops everything from that source, including data
read earlier, and keeps local results. A query for that source's target
retains only T4 if enabled. Read order does not change the result. Top-level
`reproducible` is true only if every source is `ok`, has a known HEAD, and has
`dirty: false`. A dirty tree or missing Git or HEAD alone does not cause
`incomplete`. Unavailable sources, truncation, and partial local A4 coverage
do.

T4 produces one signal per unavailable connection. `repo`, `target_repo`, and
`target` all contain its name. `code` is `T4`, `level` comes from `codes`, and
`message` explains the reason. Its level leaves slice and map exit codes
unchanged. In `lipi check`, `error` level gives exit code 1. `off` suppresses
the signal and preserves `unavailable`, `incomplete: true`, `reproducible:
false`, and coverage information.

Text reports the sources, HEAD (seven characters are sufficient), and their
state. JSON has `notes` objects with `code` and `text`. `repos-scope`
describes available sources in scope, `repos-incomplete` describes unread
sources, and `repos-unreproducible` reports dirty trees or missing Git or
HEAD. These notes and the `cross-repo-staleness` note are outside the output
budget and appear with any `--only` selection. `checks.staleness` checks only
local links to local sections and has `scope: local`. Excluding
cross-repository links alone does not cause `incomplete`. See [connected
repository examples](slice-examples.md#repos) for an external target and dirty
and unavailable neighbors.
