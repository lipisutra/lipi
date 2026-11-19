# lipi commands

Run commands from the project root. `mv` also works from a subdirectory.
`lipi …` uses the installed checker. The project keeps settings, rules, and
state (ADR-010). See [README](../../README.md) and [SETUP.md](../../SETUP.md).

## Work with a project

| Command | Purpose |
| --- | --- |
| <a id="help"></a>`lipi help` | Show help. Equivalent to invoking `lipi` without arguments or with `-h`, `--help`, `?`, or `/?`. `lipi help slice`, `lipi help map`, `lipi help mv`, and `lipi help review` show help for that command. |
| <a id="guide"></a>`lipi guide` | Print [SETUP](../../SETUP.md) from the repository or installed package. If the page is unavailable, print its address at the current version tag and exit with 1. |
| <a id="check"></a>`lipi check` | Run [quick checks](checking.md). `--staged` adds staleness checks for the Git index, and `--diff A...B` compares a revision range. `--strict` treats warnings as errors. `--no-baseline` shows all errors. |
| <a id="audit"></a>`lipi audit` | Run check and a detailed [audit](checking.md). Also reports ignored trace marker lines and review authors. `--reviews-since <revision>` shows [new review marks](checking.md#review-authors). |
| <a id="index"></a>`lipi index` | Regenerate the [workflow index files](workflow.md), including the overview, active lists, and closure log by `Closed` year. |
| <a id="baseline"></a>`lipi baseline [--prune]` | Record errors in `.agents/lipi/baseline.json` so only new errors fail checks. Warnings are excluded. `--prune` removes fixed errors without adding new ones. Commit the baseline with the project. |
| <a id="new"></a>`lipi new <type> "Title" [kind] [lipi]` | Create a document with the next ID in the creation year. ADR and feedback use flat directories. Types are `pln`, `iss`, `dsc`, `adr`, and `aud`. An issue's `Kind` is `bug`, `friction`, `request`, or `question`. Recipient `lipi` allows an issue in `.agents/lipi-feedback/` if workflow documents are disabled. |
| <a id="selftest"></a>`lipi selftest` | Run lipi's local unittest suite from its repository. A missing test directory produces a message and exit code 2. |
| <a id="version"></a>`lipi version [--path]` | Show the package version. `--path` also shows the checker path. `lipi --version` invokes the same command. |
| <a id="lang"></a>`lipi lang [language]` | Show or set the interface language for the current user. |

English is the default. Run `lipi lang ru` before the first `lipi init` for Russian
terminal output and starter files. Managed rules and CI use English. See
[interface language](settings.md#interface-language) for the scope of the setting.

```bash
lipi map                            # Targets, code layers, and tests
lipi slice docs/api.md#requests      # Slice a concept before starting work
lipi check --format json --structure  # Findings and link graph
lipi new pln "Plan title"
lipi new iss "What broke" bug
lipi new iss "What got in the way" friction lipi
```

## Review A4 <a id="review"></a>

`lipi review <path#anchor> --at <file[:line]> --full` shows an A4 pair in full
and a token. Read both sides, then confirm the token with a reviewer and a reason. `lipi review
--prune` shows a cleanup plan. See the [review reference](review.md) for
confirmation, state, JSON, and moves. Run `lipi help review` for help.

## Map the project <a id="map"></a>

`lipi map` tabulates direct trace markers by target, code layer, and test. A zero
means there are no links in that column. `lipi map --format json` returns the same
rows and counts. Run `lipi help map` for help. This is a read-only command and uses
no history or checks. See the [map reference](map.md).

## Slice before a task <a id="slice"></a>

`lipi slice <target>` gathers rules, signals, code locations, and tests for a
section, page, code file, or work item ID. It only reads data and leaves checks,
the baseline, and workflow indexes untouched.

```bash
lipi slice docs/api.md#requests
lipi slice src/api.py --format json
lipi slice ISS-007
lipi slice --diff HEAD   # Or --staged to see related locations to review
```

See the [slice reference](slice.md), [diff slice](slice-diff.md), and
[examples](slice-examples.md) for targets, blocks, limits, flags, and JSON. Exit
code 0 means the command returned a result, including an empty slice. A missing or
ambiguous target exits with 1. An invalid invocation or settings exits with 2.
Signals in a result leave its exit code unchanged.

## Move a page or directory <a id="mv"></a>

`lipi mv <old path> <new path>` moves a page or directory. `lipi mv --from <file>`
reads a list of moves. Without `--apply` the command shows the complete plan with
exact replacements. Run `lipi help mv` for help. Positional paths are relative to
the current directory. Paths within the list are relative to the Git root.
Directory and list moves require affected files to match the committed state in the
working tree and index. A single-page move preserves local edits. See
[moves](move.md) for scope, references, refusals, rollback, and exit codes.

## Output <a id="output"></a>

| Format | Purpose |
| --- | --- |
| `text` (default) | Read one line per finding, with the location, severity, check code, and message. |
| `json` | Consume one JSON object in tools or CI, using the schema below. |
| `github` | Emit GitHub Actions annotations, using `::error` for errors and `::warning` for warnings. |

```bash
lipi check --format json
lipi check --format json --structure   # Also include nodes and edges
lipi check --format github             # GitHub Actions annotations
lipi new pln "Title" --format json      # Document path and ID in JSON
```

Schema 1 reports this D1 finding for a broken link. JSON messages use English in every interface language.

```json
{
  "schema": 1,
  "version": "1.0.0",
  "errors": [{"code": "D1", "file": "docs/guide.md", "line": 12, "subject": "nope.md", "message": "link points to a file that does not exist: nope.md"}],
  "warnings": [],
  "baseline": {"known": 0, "fixed": 0},
  "summary": {"pages": 2, "docs": 0, "tags": 0, "errors": 1, "warnings": 0}
}
```

- `errors` and `warnings` contain findings. Each has the check `code`,
  project-relative `file`, `line` (0 when absent), and `subject`,
  a stable identity such as a link target, anchor, header field,
  or section. The baseline matches on `code`, `file`, and `subject`
  regardless of line shifts or wording changes.
- `baseline` counts errors it covers (`known`) and errors cleared
  since it was recorded (`fixed`). Covered errors are omitted from
  `errors`.
- `summary` counts documentation pages, workflow documents, trace
  markers, errors, and warnings.
- `structure` appears with `--structure`. Its `nodes` describe
  documentation pages, sections in other Markdown files, workflow
  documents, and marked code. `edges` include links, trace markers
  targeting sections and work item IDs, `covers`, and master-plan
  links. `counts` summarizes nodes and edges. With `--staged` or
  `--diff`, `stale` shows the staleness chain. The graph reflects links
  found by the checks. Its shape is recorded in
  `tests/fixtures/*.structure.json`.
- `new … --format json` returns `path`, the project-relative document
  path, `id`, its ID, and `index_updated`, whether the index was updated.

The `github` format emits one annotation per finding. This run reports a
broken link and an installed lipi version older than the project lock.

```text
::warning file=.agents/lipi/lipi.lock,title=V1::upgrade lipi: pipx upgrade lipi
::error file=docs/guide.md,line=12,title=D1::link points to a file that does not exist: nope.md
```

`file` is omitted if the finding has no file. `line` is omitted if the line is
unknown (0). Messages and parameter values use GitHub Actions escaping rules.
GitHub messages follow the interface language. The format includes informational lines about reviews and ignored trace marker
lines. It omits the overall summary and baseline. Use JSON for machine consumption.

The exit codes for `check` and `audit` apply to all formats.

| Code | When |
| --- | --- |
| 0 | No new errors, and no warnings when `--strict` is active. |
| 1 | New errors, or warnings when `--strict` is active. |
| 2 | Invalid invocation, such as an unknown option or format, or invalid configuration (C1). Checks did not run. |

## Project CI <a id="ci"></a>

`lipi ci github` installs the English workflow at `.github/workflows/lipi.yml`.
You can install it at setup with `lipi init --ci github`. On pushes and pull
requests, the job installs lipi at the same major version (`pipx install
git+https://github.com/lipisutra/lipi@v<major>`) and runs the installed command
with GitHub Actions annotations. V3 checks the workflow against the lock.
`lipi init` reapplies the managed workflow.

In another CI system, run one check with full Git history for pull requests.

```bash
lipi check --diff origin/main...HEAD --format github
```

CI must install the `lipi` command to run it (ADR-010).

## Diagnose a project <a id="doctor"></a>

```bash
lipi doctor
```

The command reports Python and installed lipi versions, whether `lipi.json` and
`.agents/lipi/lipi.lock` exist, the project's lock version and its major-version
compatibility, the pre-commit hook expected by `enforce`, workflow layouts and
dates, workflow index freshness, and the presence, entry count, and errors of the
baseline. Passing items end with `— OK`. A problem is marked `[problem]` and gives
the action to take. A stale index, for example, produces
`index: stale — [problem] Run lipi index`.

The command exits with 0 when all items pass and with 1 if any problem is found. It
only reads files. In a folder without setup, it suggests `lipi init`.

## Apply the installed rules <a id="update"></a>

Update the program with `pipx upgrade lipi`, then check the upgrade instructions in
[CHANGELOG](../../CHANGELOG.md) to see whether to run `lipi init`. Init applies
files from the installed package locally.

```bash
lipi init [directory]      # Initialize or apply installed rules
lipi init --dry-run         # Preview changes
lipi init --enforce         # Enforce rules in a new project
```

An existing `.agents/lipi/lipi.lock` indicates a repeat application.

| State | Action |
| --- | --- |
| Neither lock nor `lipi.json` | Create settings, missing scaffolds, and lipi files, preserving existing files. |
| `lipi.json` present, no lock | Preserve settings and scaffolds and create missing lipi files. |
| Lock and `lipi.json` present | Replace or restore managed lipi files. Preserve scaffolds and the baseline, with no creation of missing ones. |
| Corrupt lock or settings, or lock without `lipi.json` | Exit with 2 before writing. |

First-time setup creates a missing baseline and preserves an existing one. Add the
link to `.agents/lipi/README.md` to an existing `AGENTS.md`. A new scaffold comes
with the link.

`--type`, `--docs`, `--workflow`, and `--enforce` set options for a new project. If
`lipi.json` already exists, explicit arguments must match it. A mismatch exits with
an error that identifies the key to edit. `--ci github` adds the CI template. An
existing lipi CI template is reapplied even without the flag. Init regenerates the
indexes as [generated files](workflow.md#ownership).

Init uses the bundled English templates for managed rules and CI, even at
the same package version. It compares files with the lock fingerprints to
identify local edits it will overwrite. A preview reports `Will replace
your edits in .agents/lipi/README.md`. Applying reports `Replaced your
edits in .agents/lipi/README.md`.
It reconciles a hook carrying the lipi marker with `enforce` and preserves an
unrelated hook. The lock records the version, template fingerprints, and `enforce`.
Files with identical contents are left untouched. The output identifies the
installed version. `--dry-run` previews the plan without writing.

Upgrade lipi before updating a project on a newer major version. Init can
[move documents by year](workflow.md#upgrade). Use [`lipi migrate`](#migrate) for other formats.

## Friction with the rules <a id="friction"></a>

When a rule gets in the way, a check is wrong, or a capability is missing, file an
issue in that project with `Recipient: lipi`.

```bash
lipi new iss "What got in the way" friction lipi
```

With `"workflow": null` the command creates the issue and its directory under
`.agents/lipi-feedback/`; the project commits them.

To collect those issues into lipi, run this in a lipi clone, which receives the
copies; `lipi collect` works the same from an editable install:

```bash
python3 src/lipi/collect.py /path/to/project [/path/to/another ...]
```

Copies are filed in `workflow/issue/YYYY/` using today's date for `Created`. Each
is labeled `- Source: external <6 hex digits> ISS-NNN`. The hash is the first six
hex digits of SHA-256 over the UTF-8 project directory name. Repeating collection
with the same directory basename and issue ID does not create a duplicate.
Anonymize the title and body before collecting because both are copied verbatim.

## Similar issues <a id="similar"></a>

After `lipi new iss "Title"` creates an issue, it shows up to five similar issues
with `open` or `in progress` status from workflow and `.agents/lipi-feedback/`.
Review the suggestions as potentially related work. The command creates the new
issue without a duplicate decision or confirmation. It skips the new file,
archives, `skip_dirs`, and files ignored by Git. No matches produce no hint.

The command compares sets of case-insensitive Unicode words at least three
characters long. Punctuation and underscores split words. Words are used as
written, with no stemming. A match requires at least two shared words and an
intersection of at least half the union. Identical nonempty sets match even with
one word. Results sort by descending overlap, then by ID and path. JSON for `new
iss` adds `similar` with `id`, `path`, `title`, and `status` per result. No matches
produce `[]`. Other document types omit this field.

## Create a decision <a id="new-decision"></a>

`lipi new adr "Title"` creates a decision in the `decisions` directory from
`lipi.json`, or `<workflow>/adr/` by default. An explicit `decisions` directory
works with `"workflow": null`. The command creates it if missing. With unprefixed
names such as `0001-example.md`, the next name is `0002-….md`. If their widths
differ, the widest one sets the width. Without unprefixed names, the format is
`adr-NNN-….md`. Archived names reserve numbers and set the naming convention if the
active directory is empty. See the [workflow rules](rules.md#workflow). JSON
returns canonical `ADR-NNN`. The project fills in the header and body.

## Migrate workflow documents <a id="migrate"></a>

Use this command to convert plans and issues arranged in status directories such as
`current/`, `completed/`, and `backlog/`, with a manually maintained closure log
and master plan.

```bash
lipi migrate            # Preview the move and destination paths
lipi migrate --apply    # Apply the plan
```

Migration requires Git and a clean tree and applies moves through `git mv`. It
preserves IDs, accepts legacy Russian headers, and writes the English fields,
statuses, kinds, and required headings. The body remains intact. The year comes
from `Created`, the first commit, or today's date, in that order. ADR stays flat.
Migration preserves a valid `Closed` date. If it is missing, the command uses the
commit that last closed the document when Git history establishes it. It uses
`Updated` when it assigns a final status to legacy material without a standard
header or when a file has no Git history. The plan shows each date's source.
A missing required `Result` gets a placeholder such as
`- Result: Not recorded (migrated 2026-11-19)`.

The previous closure log, master plan, and reports go into `history/`.
`history/MIGRATION.md` records the move mapping. The command then regenerates the
index.

The directory comes from `workflow` in `lipi.json`. Explicitly passing a different
directory records it in settings when you apply the plan. A `null` value for
`workflow` requires an explicit directory for both preview and apply. The plan
ends with the exact command, such as `lipi migrate workflow --apply`. See the
[setup instructions](../../SETUP.md#existing-workflow).

A `migrate.json` alongside the workflow documents can override individual files.

```json
{"files": {"current/roadmap.md": {"type": "pln", "status": "in progress", "number": 7}}}
```

Keys in `files` are relative to the workflow directory. `type` is `pln`, `aud`,
`dsc`, `adr`, or `iss`. See the [agent workflow rules](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/locale/en/templates/lipi/common/workflow.md)
for the allowed `status`. `number` is a positive integer. Unknown keys, types, and
statuses exit with 2. Remove `migrate.json` after the one-time migration.
