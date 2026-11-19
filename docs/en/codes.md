# Check codes

The checker reads documentation, workflow documents, `AGENTS.md`,
project rules in `.agents/`, and links in the root `README.md`. It checks
lipi rules in `.agents/lipi/` and the CI template against the lock file's
fingerprints.

In Git repositories, including nested projects, checks use tracked and
new nonignored files within the project. New files are included before
`git add`. `.gitignore` excludes untracked files. Explicit external
documentation and workflow directories use their own Git file lists.
Outside Git, the checker scans directories. `skip_dirs` applies in both
cases. See [directory names and root-relative paths](settings.md#skip-dirs).

Quick checks must finish within two seconds on a synthetic project with
300 pages and 5,000 code files. CI verifies this with `tests/test_speed.py`.

A check code is permanent. A new check gets a new code, and a retired
code stays retired. CI, baselines, and people rely on the same meaning
across versions.

Each row has an explicit anchor, such as `<a id="d1"></a>` and
`<a id="w8"></a>`. The checker's `@trace` markers in `src/lipi/checker/`
reference these anchors so changes can be traced to their documentation.

| Code | What it checks |
| --- | --- |
| <a id="c1"></a>C1 | Settings keys, types, and values must follow the [schema](settings.md). `skip_dirs` entries must be names or paths inside the root. `decisions` must stay within the project, contain no NUL, and avoid symlinks in Git. Connections must have distinct physical roots and cannot point to the local project. With connections, layer names cannot contain `::`. Missing neighbors are allowed. Existing `.agents/lipi/lipi.lock`, `.agents/lipi/baseline.json`, and [reviews.json](review.md#state) are also validated. A failure stops checks with exit code 2. The level is fixed. |
| <a id="d1"></a>D1 | Documentation pages must be readable as UTF-8. Links must resolve to a file and anchor available within Git and read boundaries. A heading without an explicit anchor is D7. Default error, configurable via `codes`. |
| <a id="d2"></a>D2 | Explicit anchor format and uniqueness on a page. Default error, configurable via `codes`. A duplicate heading slug is a fixed warning, as described in `CODE_LEVELS`. |
| <a id="d3"></a>D3 | Documentation page size. It skips `release_notes` and decisions. Default error, configurable via `codes`. |
| <a id="d4"></a>D4 | Documentation pages must be reachable from the edition's `README.md`. Decisions are exempt. Excluded pages cannot serve as intermediate links. Default error, configurable via `codes`. |
| <a id="d5"></a>D5 | Documentation may link to decisions within the workflow directory. Other workflow links, including indexes, are violations. Default error, configurable via `codes`. |
| <a id="d7"></a>D7 | Documentation link to a heading without an explicit anchor. Workflow documents, agent instructions, and root README outside documentation use W9. With `"codes": {"D7": "off"}`, the link is accepted and its graph edge points to the page with an `anchor` field and no anchor node. T1 and D6 still require explicit anchors for section targets. Default error, configurable via `codes`. |
| <a id="d6"></a>D6 | Invalid `covers` target. It must be a root-relative path with an explicit anchor or a work item ID. T1 resolution rules apply, including ADR ID normalization, exclusions from the source root, and external targets. T4 applies to unavailable sources. Default error, configurable via `codes`. |
| <a id="l1"></a>L1 | A page has no counterpart in an existing edition listed in `required`. If the edition directory itself is missing, D4 reports its missing index. Language pairs exclude decisions, connected sources, and `skip_dirs`. Default error, configurable via `codes`. |
| <a id="l2"></a>L2 | Pages with the same relative path in different editions must have matching explicit anchor sets. Language pairs exclude decisions, connected sources, and `skip_dirs`. Default error, configurable via `codes`. |
| <a id="l3"></a>L3 | A link between editions must point to the corresponding page. Links to `decisions` are exempt. Excluded pages are skipped. Default error, configurable via `codes`. |
| <a id="w1"></a>W1 | Workflow document name, type, and directory. A document directory needs a main file readable as UTF-8. Decisions have leading digits with optional `adr-`. `skip_dirs` are excluded. Default error, configurable via `codes`. |
| <a id="w2"></a>W2 | Workflow document IDs must be unique. Leading zeroes do not distinguish ADR IDs. One physical file cannot duplicate itself. Default error, configurable via `codes`. |
| <a id="w3"></a>W3 | Document header dates, status, and kind. `Closed` must be within the range from creation through the UTC date plus one day. `Refines` must be a Markdown link to a decision. Default error, configurable via `codes`. |
| <a id="w4"></a>W4 | `Result` is required on completed or canceled plans and closed issues. `Closed` is required for all final PLN, ISS, DSC, and ADR statuses. Default error, configurable via `codes`. |
| <a id="w5"></a>W5 | Master plan size and IDs. IDs must exist, be unambiguous, and refer to nonfinal plans or issues when of type PLN or ISS. Leading zeroes in ADR IDs are insignificant, and excluded work items are unavailable. Default error, configurable via `codes`. |
| <a id="w6"></a>W6 | Broken links in workflow documents, agent instructions, or the root README, including missing files or anchors and targets excluded by Git or read boundaries. Headings without explicit anchors use W9. Default error, configurable via `codes`. |
| <a id="w7"></a>W7 | A stale file in `INDEX.md`, `index/*.md`, or `index/done/*.md`. Local `check` regenerates changed files when run outside CI, in a format other than GitHub, and without `--staged` or `--diff`. Other runs report each stale file. Excluded work stays out of the index. Default error, configurable via `codes`. |
| <a id="w8"></a>W8 | An issue with `open` or `in progress` has a nonempty `Observation`. A plan with `in progress` or `pending acceptance` has nonempty `Purpose` and `Completion criteria`. Default error, configurable via `codes`. |
| <a id="w9"></a>W9 | A link to a heading without an explicit anchor in workflow documents, agent instructions, or the root README outside documentation. Documentation uses D7. Section targets of `@trace` and `covers` require explicit anchors. Default warning, configurable via `codes`. |
| <a id="w10"></a>W10 | PLN, ISS, DSC, and AUD use type/year/document layout. ADR and feedback use flat directories. Default error, configurable via `codes`. |
| <a id="w11"></a>W11 | A directory's year must match `Created`. The finding suggests a specific move command. Default warning, configurable via `codes`. |
| <a id="t1"></a>T1 | Invalid `@trace` target. Use a project-relative `.md` section and anchor or a work item ID. Lines with `lipi: ignore-trace` are skipped. ADR IDs are normalized. A `name::target` requires a known connection and permitted `read` scope. Unknown names, missing targets, and unsupported external work types raise T1. Unavailable sources raise T4. Default error, configurable via `codes`. |
| <a id="t2"></a>T2 | Code under a trace marker changed without an update to its anchor region, or a region changed without an update to help that declares it in `covers`. The anchor region uses the same boundary as a slice excerpt, including outside documentation. Edits nearby leave the region unchanged. ID targets and cross-repository links are exempt. Graph scans include links from ADR attachments, including directories without a prefix, and skip excluded directories. Default warning, configurable via `codes`. |
| <a id="t3"></a>T3 | `@trace` or `covers` targets a work item with a final status, or documentation or agent instructions link to a superseded or rejected decision. A closed issue prompts a review of whether the link is still needed. For external decision ID targets, the message, successor, and `subject` include the connection name. See the status table below. Default warning, configurable via `codes`. |
| <a id="t4"></a>T4 | A known connection has an unavailable source. The finding gives the reason and reports that the link could not be checked. T3 is skipped. The source's `skip_dirs` are relative to its own root. Map and slice still report incomplete coverage with T4 disabled. Default warning, configurable via `codes`. |
| <a id="v1"></a>V1 | Installed lipi version versus the lock file. Different major versions raise an error. An older program in the same major version warns and suggests `pipx upgrade lipi`. For a project set up on an older major line, apply the rules following the release instructions or use a [matching installation](../../SETUP.md#install). A missing lock skips this check. Levels follow compatibility rules. |
| <a id="v2"></a>V2 | With a lock file, `AGENTS.md` must link to `.agents/lipi/README.md`. New scaffolds include the link. Add it manually to an existing file, which init preserves. Default error, configurable via `codes`. |
| <a id="v3"></a>V3 | A lipi rule or CI template differs from its lock fingerprint, or the fingerprint list is empty. Both are errors. File a lipi issue for rule changes and run `lipi init` if fingerprints are missing. An `enforce` mismatch is a warning and also calls for `lipi init`. Levels are fixed. |
| <a id="a1"></a>A1 | Audit, stale work items. Covers inactive plans, plans in `pending acceptance`, and old issues. Default warning, configurable via `codes`. |
| <a id="a2"></a>A2 | Audit, workflow document exceeds the size limit. Default warning, configurable via `codes`. |
| <a id="a3"></a>A3 | Audit, entry point matched by `entry` lacks a trace marker. Examples with `lipi: ignore-trace` do not count. Decision attachments are excluded from project code. Default warning, configurable via `codes`. |
| <a id="a4"></a>A4 | Audit, code is newer than the anchor region selected by the slice. Edits nearby leave the region unchanged. See [history and region rules](checking.md). A [review mark](review.md) can suppress a reviewed pair. Adjacent stand-alone trace markers form one group. ID targets and cross-repository links are exempt. The graph includes links from ADR attachments, including directories without a prefix. Default warning, configurable via `codes`. |
| <a id="a5"></a>A5 | Audit, a work item's `Status` and `Updated` lag behind commits that reference its ID. A nested project uses commits affecting its own files. Default warning, configurable via `codes`. |
| <a id="a6"></a>A6 | Audit, baseline size by check code, for example `baseline: D1 — 3, W6 — 1` in English. Skipped if no baseline file exists. Default warning, configurable via `codes`. |
| <a id="a7"></a>A7 | Audit, an `accepted` decision explicitly links to an `open` discussion. Check whether the discussion can close. One finding per ADR/DSC pair, with no automatic status change. Default warning, configurable via `codes`. |
| <a id="a8"></a>A8 | Audit, optional `Due` on a plan or issue with a valid nonfinal status is overdue or is an invalid YYYY-MM-DD date. Today is still on time. Final and unknown statuses are excluded. Default warning, configurable via `codes`. |
| <a id="p1"></a>P1 | A `checks` command is missing, fails to start, exits nonzero, or exceeds `timeout`. Includes the check name and last 20 lines of output. `--format github` emits an annotation without a file. Commands run from the project root without a shell, with `PYTHONIOENCODING=utf-8`. Default error, configurable via `codes`. |

See [settings](settings.md) for `checks` names, commands, modes, and
timeouts.

For T1 and D6, the file must pass [project filtering](checking.md), its
explicit anchor must be unique, and work item IDs must resolve outside
archives. `AGENTS.md` and project-owned `.agents/` files are eligible.
Excluded locations include `skip_dirs`, `.agents/lipi/`, and `history/` at
the root or within workflow or decisions. A missing, excluded, or
ambiguous target raises T1 for a trace marker and D6 for `covers`. With
`"workflow": null`, only ADR IDs from explicit `decisions` are available.

ADR IDs resolve through `decisions`, or `<workflow>/adr/` by default.
`001-…`, `0001-…`, and `adr-001-…` all mean `ADR-001`. Trace markers,
`covers`, slices, and duplicate detection normalize IDs the same way.
Distinct files with the same ID are ambiguous. Decisions are exempt
from D3, D4, and language pairing. Their headers, links, and anchors
are still checked.

T3 checks the status of a resolved ID target the same way for
`@trace` and `covers`. For example, a reference to `ISS-007 closed`
prompts you to decide whether the link still serves a purpose.

| Target type | Statuses that raise T3 | What to review |
| --- | --- | --- |
| Decision | `superseded`, `rejected` | Compare the code with the successor or reconsider its reliance on a rejected decision. |
| Issue | `closed` | Check whether the link is still needed. A temporary workaround may be removable. |
| Plan | `completed`, `canceled` | Check whether the link to that work still applies. |
| Discussion | `closed` | Compare the code with the discussion's result. |

Other valid statuses, audits, and Markdown section targets skip this
check. An invalid status raises W3. For a superseded decision, the
message identifies only the first workflow document linked from
`Result` as a successor. With no such link, the message names no
successor.

Ordinary links from documentation or agent instructions to superseded
or rejected decisions also raise T3 and prompt a review of the text.
Historical workflow links are exempt. A link to a decision section
also checks its status.

T3 is a warning by default and allows the check to continue. With
`"codes": {"T3": "error"}`, the baseline distinguishes findings by
`subject`, which contains the ID and status, such as `ISS-007 closed`.
Moving a decision from `rejected` to `superseded` creates a finding
the old baseline entry does not cover. Warnings are excluded from
the baseline. `off` suppresses T3 for trace markers, `covers`, and
ordinary links.

With `languages`, D1–D5 apply within each edition, with D4 starting
from the edition's `README.md`. L1 and L2 match pages by relative
path. L3 checks links between editions. `@trace` and `covers` resolve
from the project root, including the intended edition's directory.

V2 and V3 run when `.agents/lipi/lipi.lock` is valid, including with an
empty fingerprint list. An empty list means setup is incomplete and
V3 suggests `lipi init`. The installed lipi command runs these
checks, including when checking lipi itself. `lipi init` renders agent
instructions using `enforce` in `lipi.json` and records the selected value
in the lock. V3 reports a mismatch and suggests rerunning init.

Issues in `.agents/lipi-feedback/` use W1, W3, W4, W6, W8, and W9.
Their IDs share the sequence for `workflow/issue/` (W2). They are
excluded from the index.
