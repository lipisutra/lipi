# Project checks

See the [rules](rules.md) for the principles behind check modes, levels,
and history.

| Mode | When to run it | Result |
| --- | --- | --- |
| Quick | Run `lipi check`. Enabled on every commit with `"enforce": true`, or in CI when configured. | Findings and exit code 0, 1, or 2. The project's enforcement choice determines whether a commit can be blocked. |
| Audit | Run manually before and after complex or high-impact work, and before release. | Findings to review. |

The project chooses enforcement (ADR-011) with `enforce` in `lipi.json`.
The default, `false`, skips pre-commit installation. `lipi init` removes
an existing lipi hook in this mode. Agent instructions ask agents to
fix errors from their edits or report them. The user decides how to
handle the rest. With `true`, `lipi init` installs `lipi check --staged` to
block commits on errors. It preserves pre-commit hooks belonging to the
project. Apply a changed setting with `lipi init`. Until then, V3
reports that the rules were rendered with a different value. Check
exits with 0 for a clean run, 1 for errors, or 2 for an invalid
invocation or configuration, regardless of enforcement.

<a id="levels"></a>The project chooses severity levels (ADR-012) with
`codes` in `lipi.json`. Each configurable code can be `"error"`, `"warning"`,
or `"off"`. The defaults apply when omitted. C1 and V1 are fixed.
A level fixed by a rule takes precedence over `codes`. Duplicate
heading slugs under D2 are warnings. V3 reports fingerprint mismatches
as errors and `enforce` mismatches as warnings. For instance, `"D7": "off"`
permits links to headings without explicit anchors. Section targets in
`@trace` and `covers` still require explicit anchors. For ordinary links
in workflow documents, agent instructions, and a root README outside
documentation, the lack of an explicit anchor is [W9](codes.md#w9),
a warning. Documentation must stay accurate and uses
[D7](codes.md#d7) for this condition. The project can make W9 an error.
W6 handles broken links separately. Local `lipi check` regenerates
outdated workflow indexes. In CI, with GitHub format, `--staged`, or
`--diff`, lipi reports stale indexes as W7 without regenerating them. A
user file at an index path also gives W7.

Quick checks cover links, anchors, page size and reachability, workflow
filenames and headers, the master plan, index freshness, and trace
markers in code. Links include Markdown links and images, and HTML
`img[src]` and `a[href]` in Markdown files. Code examples and HTML
comments are skipped. With `--staged` or `--diff`, they warn if code
under a trace marker changes and the target Markdown section stays as
it was.
All commands get their file lists from Git within the project's
boundaries, including for nested projects. Tracked files and new,
nonignored files are included. Outside Git, scans follow `skip_dirs`.

Git-ignored files are skipped and cannot be targets. The scanner checks
the original path against the Git list before resolving any symlink and
checking the permitted directory boundary. Explicit external documentation
and workflow directories and `repos.read` retain their configured scopes.
A symlink alone cannot expand those scopes. Settings, managed state, and
the `mv --from` list are explicit command inputs read independently of
project content selection. For ID allocation, `new` also considers names
of ignored workflow documents without reading their contents or following
symbolic links. In a Git project, `init` and `new` refuse to create a
workflow document through a symbolic link, before writing.

`checks` commands run from the project root without a shell. A failed,
timed-out, or missing command raises P1 with its name and the tail of its
output. Use `audit` mode for slow checks.

Invalid settings raise C1 and exit with 2. V1 checks the version against
`.agents/lipi/lipi.lock`. A project set up with another major version
needs a [matching installation](../../SETUP.md#install) or the rules applied
according to the [release history](../../CHANGELOG.md). V3 checks rule and
CI template fingerprints.

Audit checks stale work items, document size, entry points without
trace markers, staleness, statuses lagging behind commits, and baseline
size. An accepted decision linking to an open discussion raises A7,
which prompts a check of whether the discussion can close. An optional
`- Due: YYYY-MM-DD` on a plan or issue raises A8 for overdue or invalid
dates. Today is still on time. Final and unknown statuses are excluded.
A7 and A8 are warnings configurable through `codes`. They leave statuses
as recorded.

Audit also counts physical lines with the exact `lipi: ignore-trace`
directive within the code scan, even if a line contains no trace marker.
JSON reports `summary.ignored_trace_lines`. Text and GitHub output include
a separate count, even zero. The count has no check code or warning,
creates no baseline entry, and leaves `--strict` unchanged. Checks
without audit keep their usual summary. The directive suppresses only
trace markers on its own line. Edits inside a real region still count
for T2 or A4, and `covers` and other checks still apply.

A4 history follows code moves between files and ignores whitespace
changes (`git blame -w -M -C`). Adjacent stand-alone trace marker lines
form one group. Their comments are excluded when dating code. An inline
trace marker forms its own group, and code beside it counts. Audit and
slice use the same group boundaries, ending at the next group or at
EOF. Messages show code and section times in UTC. Uncommitted lines use
one timestamp for the whole check. A concurrent edit to code and its
target section is therefore considered simultaneous and produces no A4.
An edit to code alone is still compared with the committed section.

Audit and slice use the same selection procedure. File history and
blame without `-C` identify regions that are already up to date. Other
regions use `-C` on the whole file so move detection has context. A
region that cannot be safely excluded needs an individual check. Audit
checks every file. Slice limits individual blame and reports unchecked
locations as described in the [slice reference](slice.md#staleness).
Only verified staleness produces A4.

[Confirm a review](review.md#confirm) for one A4 pair after examining
both regions. `.agents/lipi/reviews.json` stores their fingerprints,
a reviewer, and a reason. Audit and slice suppress only the matching
pair. Either side changing invalidates the mark. Review marks also
apply to A4 at `error` level. They leave T2 and covers checks unchanged.
[Review counters](review.md#summary) are separate from findings and the
baseline. Keep documentation dates tied to actual edits.

The baseline `.agents/lipi/baseline.json` records existing project debt.
`lipi baseline` records current errors. `lipi baseline --prune` removes
fixed errors without adding new ones. Checks fail for errors beyond the
baseline. Warnings and C1 configuration errors are excluded.

The checker verifies form. People judge whether the text accurately
describes behavior.

For tools and CI, `lipi check --format json` returns errors, warnings,
and a summary in one JSON object. `--format github` emits GitHub Actions
annotations. With `new`, JSON returns the created document's path and ID.
`--structure` appends a graph with nodes for pages, explicit anchors,
workflow documents, code files with trace markers, and rules. Edges
come from links in documentation, workflow documents, instructions,
and README, as well as `@trace`, `covers`, and master-plan links. `counts`
breaks them down by type. `--staged` or `--diff` also includes the `stale`
chain. The check set and codes stay the same.

## Reviewers and comparison to a revision <a id="review-authors"></a>

When `reviews.json` exists, audit adds a `reviewed_by` array to the
summary with `{reviewer, count, last_reviewed_at}` for reviewers whose
marks suppressed A4 on this run. The sum of `count` equals
`reviewed_pairs`. Unapplied marks are omitted. With `A4: off` the array
is empty. Reviewer names keep their exact form, ordered by `reviewer`.
`last_reviewed_at` is the latest UTC timestamp among that reviewer's
entries. An empty registry produces `[]`. Without the file, a regular
audit keeps its usual fields.

```bash
lipi audit --reviews-since HEAD
lipi audit --reviews-since <revision> --format json
```

The flag accepts one Git commit revision, including an annotated tag.
Revision ranges are unsupported. You can pass `--root` for a project
inside a repository. The command compares the current working-tree
registry with the project's `.agents/lipi/reviews.json` at the selected
commit. A missing historical file means an empty registry. A missing
current file means zero new entries.

A current entry is new if its `id` was absent from the old registry.
The comparison includes **the entire registry**, even stale or unapplied
marks, so the number of new entries can differ from the number of
suppressed A4 pairs. Changing reviewer, timestamp, or explanation
while keeping the same `id` creates no new entry. A change to an address
or fingerprint changes `id` and counts as new. The comparison does
not determine code authors, project releases, or reviewer independence.

The flag adds `summary.reviews_since` to JSON even without a current
registry. `revision` is the supplied value, `commit` its full OID,
`count` the number of new entries, and `by_reviewer` the same breakdown
by reviewer. Empty results are `0` and `[]`. These statistics leave
findings, exit codes, and `schema: 1` unchanged. `check --audit` is
equivalent to audit. The flag is invalid with ordinary check, index,
new, baseline, or slice, which get no new fields.

This `summary` fragment shows two applied pairs and one new entry.

```json
{
  "reviewed_pairs": 2,
  "reviewed_by": [
    {
      "reviewer": "Ирина",
      "count": 2,
      "last_reviewed_at": "2026-11-18T12:30:00Z"
    }
  ],
  "reviews_since": {
    "revision": "HEAD~1",
    "commit": "4525f5c61e9e210bb88b863de30d95013b5e275d",
    "count": 1,
    "by_reviewer": [
      {
        "reviewer": "Ирина",
        "count": 1,
        "last_reviewed_at": "2026-11-18T12:30:00Z"
      }
    ]
  }
}
```

Text and GitHub formats show reviewers and revision comparison on
separate informational lines with counts and timestamps. Names and
revisions are JSON-quoted, with control characters escaped so each
entry fits on one line. An invalid revision, unavailable Git, or
unsupported command is an argument error with exit code 2. A corrupt
historical registry, directory, or symlink in its place raises C1 and
exits with 2 before any partial result. Historical and current files
undergo the same schema check. Argument and snapshot validation happen
before project checks and index regeneration. The current registry is
left untouched.
