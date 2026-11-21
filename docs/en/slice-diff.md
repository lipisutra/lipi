# Slice by Git diff

After an edit, `lipi slice` shows the related code locations, decisions, and tests to check. A link is a reason to review the other end. See the [slice contract](slice.md) for blocks, signals, the output budget, and the response schema.

## Selecting changes <a id="selection"></a>

```bash
lipi slice --diff HEAD
lipi slice --diff v1.0.0 --format json
lipi slice --staged
```

Choose one source from a target, `--diff <base>`, and `--staged`. With one Git revision as its base, `--diff` examines both staged and unstaged changes to tracked files in the working tree. Stage untracked files to include them. `--staged` compares the index with HEAD, or with the empty tree before the first commit. In this mode, changed contracts and their wording come from HEAD and the index.

Reading a diff leaves files and the index untouched and does not run project checks. The code scan excludes Markdown, binary files, oversized files, documentation, workflow and decision directories, and files excluded by the trace marker scan. A pure rename with no line edits adds no targets.

For Markdown files eligible as marker targets, added lines belong to anchor regions in the new page and deleted lines to regions in the old page. The boundaries are the same as for [A4](codes.md#a4). For example, editing a subheading affects its enclosing marked section, and editing a table header affects each marked row in the table.

On each side of the diff, a trace group covers the lines up to the next group or the end of the file. Added lines use their new markers. Deleted lines use the old ones, even if the marker or the whole file was removed. For a code-only diff, target paths and work item IDs resolve against current project documents. When a contract changes, the slice can also find local markers that referenced its old address on the earlier side. Connected repositories supply locations from their available working trees.

## Response <a id="response"></a>

Blocks follow the order `signals`, `obey`,
`concepts`, `entry`, `code`, `tests`, `context`. Concepts include the changed
sections and the resolved targets of affected markers, with their titles
and code location counts. As in an ordinary slice, these targets supply
applicable decisions, instructions, refinements, and related documents.
The code and test blocks list other locations marked for the affected targets
and include a changed declaration if it links to a changed contract. Each
shared concept, decision, or location appears once. The [repository connection
rules](slice.md#repos) govern external targets and consumers.

Code-only diffs with multiple targets list matching targets after `via`
in `entry`, `code`, and `tests`. Locations linked to changed contracts
carry their targets and reasons, including whether a marker now points to the
new address or still points to a deleted anchor. In a diff with multiple
targets, lipi shortens an address to `#anchor` if that anchor identifies one
target before filtering and truncation. Shared anchors and targets without
anchors use their full addresses.

The summary prompts you to review related locations and counts unmarked
code changes. An unmarked location is a continuous run of changed code lines
with no resolved target. Edits in eligible Markdown outside explicit anchor
regions have their own count. For each diff hunk, each count uses the larger
number of runs on either side, so a replacement counts once.

The summary covers the slice before truncation. A4 and T3 appear as ordinary
signals. The staleness check uses current linked locations and the usual
[limits](slice.md#staleness). An empty diff or one without linked locations
returns 0. Missing Git, an invalid base, or a diff read error returns 2.

A valid [review mark](review.md) suppresses A4 for its pair and keeps the pair in the coverage count. Review marks do not affect T2 checks.

## Section excerpts <a id="excerpts"></a>

In text, the Changed sections block appears after signals, rules, and
decisions, before concepts. It shows the wording before and after the edit,
including sections where lipi found no linked locations. All sections and
both sides share `max(1, slice_budget // 3)` lines within the
[overall budget](slice-output.md#budget). To see excerpts and any signals,
use `--only excerpt`. A `--only` list without `excerpt` hides them. Use
`--full` to include the full wording outside the budget.

## JSON <a id="json"></a>

The schema version is 1. The target has `kind: "diff"` and a `target` value of `--diff BASE` or `--staged`. The [ordinary slice schema](slice-output.md#json) supplies the common fields, including `repo` and source metadata when connections are configured.

Each `entry`, `code`, and `tests` item has `matched_targets` with all distinct
targets shared by its markers and the diff, even if there is only one. The
list contains canonical addresses, including connection prefixes for
external targets, in lexicographic order by full address. The existing
`via` string in `entry` and `code` is `matched_targets[0]`.

For eligible Markdown edits, `checks.diff.unanchored` counts runs outside
explicit anchor regions. Each shown item in `checks.diff.sections` has the
section's `target` and `before` and `after` text. `null` means that the section
is absent on that side. `linked: false` means lipi found no linked locations
before output filters. If any lines in a shown section were cut, `omitted`
contains the counts `before` and `after`. A side can be an empty string if
its lines were all cut. When the budget drops entire sections,
`checks.diff.sections_omitted` counts them. Either kind of truncation sets
`incomplete: true`.

A location's `reasons` identify the target and why it appears: `contract-change`
for an edited section, `target-removed` for a deleted target, `decision-number`
for a marker referencing an edited decision by ID, and `code-change` for
changed code. For a contract link, `link` describes what happened to the
marker. For example, a test that still points at a deleted anchor has reason
`target-removed` and link `retained`. Dropping the marker gives `removed`;
introducing it gives `added`. If the location exists only on the earlier
side, `side: "before"` identifies the source of its path and line number.

```json
{"checks": {"diff": {"mode": "diff", "base": "HEAD", "files": 2, "unmarked": 1}}}
```

`files` counts affected code files, including renames with no line edits.
`unmarked` counts code runs without a resolved target. With `--staged`,
`mode` is `staged` and `base` is `null`. The `cross-repo-staleness` note counts
each related location with a cross-repository link once before output
filtering. Notes `diff-review`, `diff-unmarked`, and, when there are edits
outside anchors, `diff-unanchored`, remain visible for all `--only` values.
A read error returns `{"schema": 1, "error": "invalid-diff", "message": "Git: fatal: Needed a single revision"}`.
Conflicting arguments produce a CLI diagnostic and exit code 2.

When `reviews.json` exists, `summary.reviewed_pairs` counts suppressed A4 pairs
before truncation and `--only`, as in an [ordinary slice](review.md#summary).

## Changing documentation and code together <a id="mixed-example"></a>

In `docs/export.md`, change the anchor from `#row` to `#record` and replace
“Write the name before the identifier” with “Write the identifier before
the name.” Update the marker on `write_row` in `src/export.py` to point to
`docs/export.md#record`. The marker on `test_read_row` in
`tests/test_export.py` still points to `docs/export.md#row`.

```bash
lipi slice --diff HEAD
git add docs/export.md src/export.py
lipi slice --staged --format json
```

Both slices show the old wording under `docs/export.md#row` and the new
wording under `docs/export.md#record`. The text location blocks show what
happened to each link.

```text
Code locations
  src/export.py:1  def write_row():  [src] — code change, #record (link added), #row (link removed)
Test locations
  tests/test_export.py:1  def test_read_row(): — #row (link to a deleted target)
```

In JSON the `#row` entry has `after: null` and the `#record` entry has
`before: null`. The test's `reasons` contains this item.

```json
{"target": "docs/export.md#row", "reason": "target-removed", "link": "retained"}
```

The separate `lipi check` command reports [T1](codes.md#t1) for the test
marker. See also the [code-only example](slice-examples.md#diff).
