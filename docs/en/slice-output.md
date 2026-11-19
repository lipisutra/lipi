# Slice response schema and limits

This page covers JSON fields, history, and content selection. See the
[slice reference](slice.md) for targets and block contents.

## Staleness checks <a id="staleness"></a>

The documentation date uses the same lines as the [excerpt](#budget).
The anchor region is a heading and its section, a paragraph, a list
item, or a table row and header. Lines between the header and selected
row are outside the region. T2 and A4 use the same boundary, so adjacent
edits cannot hide staleness.

The shared Git history filter covers every location. If a file has not
changed since its section, the check can rule out staleness. These
locations count toward `checked` and use none of the individual check
budget. Renames count as changes. Dirty files and files with inconclusive
history go to individual checks.

The remaining files have two fixed limits. A basic blame without `-C`
runs on up to 64 files, and a blame with precise move detection runs on
up to 16 of those. The deterministic order is entry points, other code
locations, then tests. Within each group, order is by path and line
regardless of layer order. The command counts each file once and checks
all its regions. The limits are fixed counts. `lipi audit` checks every
location without these limits.

Only verified staleness produces a signal. When coverage is partial,
the summary always shows the checked and total counts and points to
`lipi audit` for the full check. In JSON this appears in `notes` with the
code `staleness-partial` and under `checks.staleness`.

```json
{"state": "partial", "checked": 16, "total": 21}
```

`total` counts unique locations, meaning trace marker groups, with trace
markers targeting the slice's sections. It includes tests. A file slice
also counts locations in the file itself. A diff slice counts only the
other related locations. A location with several trace markers counts
as checked after all its links to the slice's sections have been checked.
Unavailable history leaves a location unchecked. With A4 disabled, both
`total` and `checked` are 0.

`state` is `full` when the check covers every location, `partial` when
some are unchecked, or `no-git` when Git is unavailable. For `no-git`,
`checked` is 0. A project in a repository subdirectory uses the
repository's history, so A4 and review marks work as at the root. A
missing scan file list alone does not trigger `no-git`. A `full` state
with a nonzero `total` also shows the checked and total counts
(`notes[].code` is `staleness-full`). `--only`, `--layer`, `--full`, and
the output budget leave history coverage unchanged.

## Output budget <a id="budget"></a>

- `slice_budget` sets the total content line budget across the response.
  It must be an integer of at least 1 and defaults to 60. Invalid
  values raise C1. The target line, summary, block headings, `notes`,
  and omission notices do not use this budget.
- An item uses one line, even when a supporting document has several
  `via` entries. An excerpt uses its own line count, up to
  `max(1, slice_budget // 3)`.
- **Excerpt boundaries.** A heading anchor's excerpt runs from its
  heading up to the next heading of the same or higher level. A table
  anchor includes the header row and its own row. An anchor in a
  paragraph or list item includes that paragraph or item. A decision
  queried by ID uses its `Decision` section.
- **Excerpt truncation.** An excerpt that fits is complete. A longer
  excerpt keeps the first paragraph, subheadings, and lines containing
  links in their original order, with a truncation notice. If the
  excerpt starts with a list, it keeps the first item including any
  continuation. Headings and links inside fenced code blocks do not
  affect selection. If the selected lines still exceed the allowance,
  they are truncated to fit. `--full` returns the full excerpt and
  uses none of the budget allocated to the other blocks.
- **Allocation.** Lines are allocated in output order.
  1. `error` and `warning` signals receive up to half the budget
     (`slice_budget // 2`, with a minimum of 1). Any remaining ones
     go first in step 3.
  2. Each nonempty block other than signals, and the excerpt, receive up
     to three lines; `info` signals receive up to three lines within the
     signal block. `error` and `warning` signals are served in steps 1
     and 3.
  3. The remaining lines go to blocks in output order, with the excerpt
     capped at its allowance.

  When there is too little space for every block in step 2, lines are
  assigned in output order. Whenever the budget allows, this reserves
  space for tests even if there are many code locations or open work items.
- The end of each block reports the number of omitted items and the
  flags to show them.
- The summary counts every confirmed signal. The signals block reports
  omissions and offers `--only signals` to show more.
- `--only` retains the selected blocks and always includes signals. The
  budget still applies. With `--only signals`, signals receive the whole
  budget. `--layer` filters `entry`, `code`, and `tests` by layer and can
  be repeated.
- JSON and text select exactly the same items and excerpt lines.

## Empty slices <a id="empty"></a>

| Case | What the note conveys | `notes[].code` |
| --- | --- | --- |
| No trace markers for a section or page | Search the code directly. | `no-marks` |
| Decision with no trace markers | No code was found for this decision. | `no-code` |
| Work item with neither links nor trace markers | Nothing links this work item to other locations. | `work-empty` |
| Code file with no trace markers | No concepts were identified. Search the code directly. | `file-no-marks` |
| No trace markers in some layers | The note names the layers without trace markers. | `layers-no-marks` |
| Git unavailable | Staleness checks require Git. | `no-git` |

## JSON <a id="json"></a>

Top-level fields are `schema` (currently 1), `target`, `summary`, `blocks`
in output order, `incomplete` (items are omitted, the excerpt was
truncated, or history was only partly checked), `notes`, and `checks`.
Each block contains `kind`, `items`, `omitted` (the omitted count), and
`hint` (flags to show omitted items). Item fields are listed below.

| Item | Fields |
| --- | --- |
| Code location | `path`, `line`, `symbol`, `layer`, `via` (the trace marker used to find it) |
| Test | `path`, `line`, `symbol`, `layer` |
| Document | `target` (`path#anchor` or work item ID), `title`, `relation` (`link` or `mark`), `status` only for work items, `depth` in `context`, `code_count` in `targets`, `via` as a list of targets in `obey` for a work item slice |
| Signal | `code` (`null` for an open work item), `level`, `message`, `target`, and `path` and `line` when there is a location |
| Concept | `target`, `title`, `code_count` (code locations across the project) |
| Excerpt | `text`, `lines`, `cut` |

For `Refines` links, `relation` is `link` and the target is the canonical
decision ID, such as `ADR-001` for `0001-….md`.

Adding a field is compatible. Removing a field or changing its meaning
requires a new `schema` number and a major lipi release.
