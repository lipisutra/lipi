# lipi rules

These rules keep project documentation aligned with the code, small enough
to navigate, and usable by people and AI agents. The checker enforces each
rule that is not covered by the agent instructions.

## 1. Three layers <a id="layers"></a>

| Layer | Where | What it covers | When it must be accurate |
| --- | --- | --- | --- |
| Documentation | `docs/` | What the project does and how to use it | Always |
| Workflow documents | `workflow/` | Plans, issues, discussions, decisions, and audits | As of the document's date |
| Rules | `AGENTS.md`, `.agents/lipi/` | How to change the project | Always |

Each layer has its own purpose.

- Documentation covers the project and can link to decisions. It leaves
  work history and workflow indexes to the workflow directory.
- Workflow documents link to documentation for facts about the project.
- Agents read the rules for changing the project separately from user
  documentation.

Change the directories in [settings](settings.md). Workflow documents can
live in a neighboring repository. `decisions` selects the project
directory for decisions and defaults to `<workflow>/adr/`. Their headers,
links, and anchors are checked. D3 size and D4 reachability checks skip
decisions even inside documentation.

## 2. Principles <a id="principles"></a>

1. **Each fact has one owner.** Explain it fully in one place and link to
   it elsewhere. A work item's document header owns its status.
2. **Documentation describes the present.** Workflow documents record how
   the project got there.
3. **Address sections by anchor and work items by ID.** Links keep
   working when a heading changes.
4. **Every rule has a check or appears in the agent instructions.**
   The checker handles routine checks. People judge the meaning.
5. **Generate summaries from their sources.** The index and closure log
   derive from document headers and stay in sync with them.
6. **Create documents when needed.** For ordinary work, make the change,
   verify it, and report the result. Create a plan, audit, or discussion
   when requested.

## 3. Documentation <a id="description"></a>

- `docs/README.md` is the default entry point. Every page must be reachable
  from it by following links.
- HTML `img[src]` and `a[href]` in Markdown follow the same link rules.
- Linkable sections use explicit anchors, for example
  `## Heading <a id="korotkoe-imya"></a>`.
- An anchor is unique within a page. A link or trace marker includes
  the page.
- Each page has a size limit. Split oversized pages by independent task.
- Set `release_notes` to identify the release history page. The size
  limit skips that page and the other documentation checks still apply.
- Remove the old page when it is moved or deleted.
- Code links are optional. A comment such as
  `@trace path/page.md#anchor` targets a section in any project
  `.md` file by its project-relative path. `@trace ADR-018` targets a
  workflow document by ID. When code under a section trace marker
  changes, the checker prompts you to reread the section (T2, or A4
  during an audit). Those checks skip work item IDs. An anchor region
  comprises a heading through the next heading of the same or higher
  level, a paragraph, a list item, or a table row and its header.
  Editing adjacent text leaves the region's date unchanged.
- Mark a literal trace marker example with `lipi: ignore-trace` on the
  same physical line. That line creates no link or region boundary and
  leaves nearby lines unaffected. It still counts as code for T2 and A4.
  The checker, slice, map, A3, and move use this rule. Audit reports
  the count of ignored example lines.
- Each language edition has its own directory and `README.md`. Paired
  pages have the same relative path and explicit anchors. Required
  editions contain all pages. Links between editions may point only
  to a corresponding page (L1–L3).

`@trace` and `covers` resolve targets the same way. An explicit anchor
must be unique within the file. `AGENTS.md` and project-owned files
under `.agents/` are eligible. `skip_dirs`, `.agents/lipi/`, and
`<workflow>/history/` are excluded. ID lookup skips archives. With
`"workflow": null`, only decision IDs from an explicit `decisions`
directory are available. An invalid trace marker target raises T1.
An invalid `covers` target raises D6.

External trace markers and `covers` use a connection prefix, such as
`core::docs/api.md#request` or `core::ADR-018`. The project declares
connections in `repos`. Reads follow `read` scopes and stay within the
neighbor's root and exclusions. A third repository is out of scope.
Documentation sections require `docs` and all forms of decision targets
require `decisions`. External plans, issues, discussions, audits, and
agent instructions are unsupported. An unavailable source raises T4.
An invalid target in an available source raises T1 or D6. T2 and A4
compare locations within a repository.

T3 warns when an `@trace` or `covers` target is no longer in effect.
Review the code and whether the link still applies. For statuses,
suggested actions, and levels, see the [T3 reference](codes.md#t3).
Ordinary links from documentation and agent instructions to superseded
or rejected decisions also raise T3 and prompt a review of the text.
Historical links in workflow documents are exempt.

See the [agent documentation rules](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/locale/en/templates/lipi/common/documentation.md).

## 4. Workflow documents <a id="workflow"></a>

| Type | Prefix | Directory | Statuses |
| --- | --- | --- | --- |
| Plan | `pln` | `plan/YYYY/` | `new`, `in progress`, `pending acceptance`, `deferred`, `completed`, `canceled` |
| Issue | `iss` | `issue/YYYY/` | `open`, `in progress`, `closed` |
| Discussion | `dsc` | `discussion/YYYY/` | `open`, `closed` |
| Decision | `adr` | `adr/` | `proposed`, `accepted`, `superseded`, `rejected` |
| Audit | `aud` | `audit/YYYY/` | None required |

- Use a name such as `pln-001-korotkoe-imya.md`. IDs are permanent and
  unique across years and archives.
- In the decision directory, `001-…`, `0001-…`, and `adr-001-…` all
  mean `ADR-001`. Multiple files with the same ID make it ambiguous.
  `lipi new adr` respects the existing number width and omitted prefix.
- Archived decision filenames reserve IDs without reading their contents.
  The command recognizes `adr-NNN-…` in the workflow directory and in
  root-level `history/`. It recognizes bare IDs in `adr` directories,
  directories named after the configured decision directory, or that
  directory's `history/`. Keep the prefix or directory when archiving.
  Active filenames determine the naming convention when present.
  Archived filenames determine it when the active directory is empty.
- The directory represents the type. A status change leaves the document
  and any incoming links in place. The year for PLN, ISS, DSC, and AUD
  comes from `Created`. ADR and feedback use flat directories. W10
  flags an invalid layout. W11 flags a mismatched year and suggests
  a move.
- The format always uses English, regardless of document language.
  Header fields after the title include `Created`, `Updated`,
  `Status`, and `Result`. `Status` contains exactly one listed value.
  `Closed` is required for final statuses, which are `completed` or
  `canceled` for plans, `closed` for ISS or DSC, and `superseded` or
  `rejected` for ADR. A missing date raises W4. An invalid date, a
  date before `Created`, or one more than a day after the UTC date
  raises W3. Record it at closure, preserve it through later edits,
  and set a new date when closing again. Audits have no closure date.
- A refining decision uses `- Refines: [ADR-NNN](path.md)`. The line
  can repeat. Refinement leaves the original decision's status intact.
  Only this relation adds related accepted decisions to the slice's
  `obey` block. An ordinary link between decisions remains context.
- **Required sections.** An issue marked `open` or `in progress` needs
  a nonempty `Observation`. A plan marked `in progress` or
  `pending acceptance` needs nonempty `Purpose` and
  `Completion criteria`. Missing or empty sections raise W8.
- **Issues** record bugs, friction, requests, or questions left for
  later. The header records the `Kind` as `bug`, `friction`, `request`,
  or `question`. After creation, `lipi new iss` suggests similar open
  issues for review. See [how similarity is calculated](commands.md#similar).
- **Closed discussions** preserve the body and result as of closure.
  Use a new discussion or decision with a link to the previous one if
  the conclusion needs an update. [`lipi mv`](commands.md#mv) can rewrite
  link addresses mechanically as part of a move.
- **lipi feedback.** With `"workflow": null`, file issues about lipi in
  `.agents/lipi-feedback/`. The checker treats them as issues. Their
  IDs share a sequence with `workflow/issue/`, and `lipi collect` imports
  them into lipi.
- **Indexes and the closure log** are built from headers. The set has a
  short `INDEX.md`, active lists, and closure pages by year. See the
  [workflow index reference](workflow.md) for the full set, log dates,
  file ownership, and regeneration.
- **The master plan** `masterplan.md` lists only upcoming work the user
  has chosen, with its order and dependencies, one line per item.
  Completed work raises an error there. The file has a size limit.
- `history/` is the archive. Regular reads and checks skip it.

See the [agent workflow rules](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/locale/en/templates/lipi/common/workflow.md).

## 5. Agent instructions <a id="executor"></a>

`lipi map` reports trace markers across layers and tests. `lipi slice`
gathers rules, signals, code, and tests for a target. Run it with
`--diff` or `--staged` to see references worth reviewing after a change.
These are read-only tools. A slice reports incomplete results so you
can continue reading and verifying the relevant files. With `repos`,
both commands show permitted references and read coverage. An external
decision explicitly marked in local code appears in `obey` with accepted
refinements from the same source. External agent instructions are
excluded. An unavailable source contributes no results. T4 leaves
reference command exit codes unchanged, while `check` exits with 1 for
T4 at `error` level. See [map](map.md) and [slice](slice.md).

`AGENTS.md` is a short entry point for people using or changing the
project. It links to `.agents/lipi/README.md`, as checked by V2. Keep
project rules in project-owned files such as `.agents/README.md`. lipi
leaves those files to the project.

`lipi init` preserves an existing `AGENTS.md` and prompts the project
to add the rules link. A new scaffold includes the link.

`.agents/lipi/` contains lipi's English task, documentation, and workflow
rules and the lock file with their fingerprints. Report friction with these
rules as an issue to lipi. V3 detects rule and CI template fingerprint
mismatches. V2 and V3 require a lock file. An empty fingerprint list
raises V3 and requires `lipi init`. The installed command contains and
runs the checker (ADR-010).

To change the rules, explain the friction in one sentence, estimate
how many documents the change affects, and update the rule, checker,
and documents in one commit. Resolve any exceptions explicitly.

See the [lipi agent instructions](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/locale/en/templates/lipi/common/README.md).

## 6. Checker <a id="checker"></a>

Quick checks verify project structure and references. Audit adds
history and work item state. Choose enforcement with `enforce` and
severity levels with `codes`. The checker verifies form. People review
meaning. See [project checks](checking.md) for modes, the baseline, and
machine-readable output.

A [review mark](review.md) suppresses A4 after reviewing one pair and
records fingerprints for both sides, a reviewer, and a reason. New
changes invalidate the mark. T2 still applies. Keep documentation
dates tied to actual edits.

## 7. Project type <a id="project-type"></a>

- **Package.** Developers are the audience for `docs/`, which serves
  as both system documentation and user documentation.
- **Application.** End users read help in `docs/`, while developers
  read and maintain the system documentation in `docs/development/`.
  A help page declares the targets it explains, using the same forms
  as trace markers: a root-relative path with an anchor or a work
  item ID. For example,
  `<!-- covers: docs/development/rules.md#skidki, ADR-018 -->`.
  Separate multiple targets with commas. When a section changes,
  the checker prompts a review of help pages that reference that
  exact page and anchor.

Application mode follows the package model and has yet to be verified
on a real application.

## 8. Outside the checker <a id="not-covered"></a>

- Translation accuracy. Language editions are checked for matching
  pages and explicit anchors.
- Agreement between documentation and public API signatures.
- Executable examples.

Projects can add checks for these based on their language and stack.
