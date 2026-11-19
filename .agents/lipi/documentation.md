# Documentation

Applies to `docs/en/`, the root README, and examples.

## Owner of a fact <a id="owner"></a>

Each fact has one owner, the page where it is described in full. Other
pages provide context and a link. Keep parameter tables, procedures,
and limitations in their owning pages.

## Current behavior <a id="present"></a>

Describe how the project works today. Keep progress, acceptance dates,
plan numbers, and past alternatives in workflow documents. When a page
moves or goes away, remove the old page.

## Anchors and links <a id="anchors"></a>

- Link to a section by its explicit anchor, as in
  `## Heading <a id="short-name"></a>`. Keep the anchor stable when you
  change the heading text.
- An anchor uses lowercase Latin letters, digits, and hyphens and must
  be unique in its file.
- HTML `img[src]` and `a[href]` in Markdown follow the same rules as Markdown links.
- Every page must be reachable by following links from `docs/en/README.md`.

## Size <a id="size"></a>

Split a page that exceeds the checker's limit into pages for independent
tasks.

## Links to code <a id="trace"></a>

Code and tests can optionally carry a comment with the path to a section
in any project Markdown file or a workflow document ID:

```
// @trace docs/en/page.md#short-name
// @trace ADR-018
```

Mark a literal trace example with `lipi: ignore-trace` on the same physical
line. It suppresses all traces on that line. Other lines are unaffected.
The line creates no link or region boundary and cannot serve as a trace
for A3. It still counts as code inside a real T2 or A4 region. Checks,
slices, maps, and moves use this rule. Audits report the number of these
lines for reference.

A path is relative to the project root. The anchor must be explicit and
unique in its file. `AGENTS.md` and project-owned files in `.agents/` are
valid targets. `skip_dirs`, `.agents/lipi/`, and `<workflow>/history/` are
excluded. Skipping `.agents/` while scanning code does not by itself
disallow targets there.
A document ID is looked up in the workflow documents outside the archive.
Decisions use the configured `decisions` directory, which defaults to
`<workflow>/adr/`. The filenames `001-…`, `0001-…`, and `adr-001-…` all
mean `ADR-001`. With `"workflow": null`, only decisions in an explicitly
configured `decisions` directory are available. An invalid trace target
gives T1.

An anchor region can be a heading and its contents up to the next heading
of the same or higher level, a paragraph, a list item, or a table row and
its heading row. T2, A4, and slice excerpts use these same lines. Neighboring
text outside the region does not update it.

Put a trace on the relevant entry point or the test that verifies the
documented behavior. T2 reminds you to reread the target section when
changing code. A4 does so when Git history shows that the code is newer
than the section. This applies to sections outside the documentation too.
T2 and A4 skip targets by document ID. For A4, uncommitted changes to both
code and a target section count as simultaneous. Changes to code alone
are still compared with the date of the committed section.

In user help, `covers` uses the same target syntax and rules:
`<!-- covers: docs/en/page.md#short-name, ADR-018 -->`.
An invalid `covers` target gives D6.

A connection under `repos` allows external targets such as
`core::docs/api.md#request` or `core::ADR-018` in both traces and `covers`.
Access to documentation requires `read: docs`. Access to decisions
requires `decisions`, including access by path and anchor. External
targets cannot refer to other types of workflow documents or another
project's agent rules. An unavailable source gives T4 when lipi cannot
check the link. Use `codes` to control its level. Check the source path,
settings, and version. Read external targets when changing linked code
because T2 and A4 run only within a repository. A slice includes the
explicitly traced external decision and its accepted refinements in the
same source. Agent rules stay within the project that installed them.

T3 warns if a target by ID is no longer active. It covers superseded and
rejected decisions, closed issues and discussions, and completed and
canceled plans. It applies to both `@trace` and `covers`. Markdown
sections, audits, and other valid statuses produce no T3 finding.
Check the code and whether the link still applies. Review whether links
to closed issues are still needed. Remove the link if it only tracked a
temporary workaround. Compare the code with the new decision or the
outcome of the work. For a superseded decision, the hint names the first
workflow document linked from its `Result` field, if present. Control T3
with `codes`: `warning` by default, `error`, or `off`.

Links from documentation into the workflow directory, including indexes,
are allowed only for decisions (D5). A normal link from documentation or
agent rules to a superseded or rejected decision also gives T3. Review
the referring text for accuracy.

## Before committing <a id="before-commit"></a>

Verify names, signatures, and behavior against the code and a test. The
checker verifies the form. A person verifies the meaning.
