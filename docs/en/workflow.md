# Workflow index

The document header stores a work item's status and result. `lipi index`
builds an overview and separate lists from these headers. See the
[workflow rules](rules.md#workflow) for filenames, year directories, and
header fields.

## 1. Index files <a id="files"></a>

Paths are relative to the `workflow` directory configured in `lipi.json`.

| File | Contents |
| --- | --- |
| `INDEX.md` | Work items marked `in progress`, plans marked `pending acceptance`, counts, and links to lists |
| `index/plans.md` | Plans with status `new`, `in progress`, `pending acceptance`, or `deferred` |
| `index/issues.md` | Issues with status `open` or `in progress` |
| `index/discussions.md` | Discussions with status `open` |
| `index/decisions.md` | Decisions with status `proposed` or `accepted` |
| `index/audits.md` | All audits |
| `index/done/YYYY.md` | Work items closed in that year with a final status from the table below |

An active work item can appear in both the overview and its own list. The
overall count includes each document once. Accepted decisions remain in
effect and appear in `decisions.md`. The index excludes issues under
`.agents/lipi-feedback/` and archived documents.

The generator creates the fixed files even when their lists are empty.
It skips Git-ignored paths when reading, writing, and linking the index.
An existing year page that becomes empty stays in place so links to that
year keep working. The page says `No closed work items.` Index headings and notices stay in English
regardless of the interface language. Work item titles and results come from the source documents.

## 2. Closure year and result <a id="closure"></a>

| Type | Final statuses |
| --- | --- |
| Plan | `completed`, `canceled` |
| Issue | `closed` |
| Discussion | `closed` |
| Decision | `superseded`, `rejected` |

The year in `done/YYYY.md` comes only from the `- Closed: YYYY-MM-DD` line.
Only the listed statuses count as final for their respective types.
Audits have no final status or closure date.

A missing required date raises [W4](codes.md#w4). An invalid calendar
date, a date before creation, or a date more than one day after today's
UTC date raises [W3](codes.md#w3). The one-day allowance accounts for time
zones and applies equally to checks, indexing, and workflow moves. A
final document without a valid closure date leaves the entire index
unchanged.

The generator reads dates from headers and leaves the headers untouched.
The closure date in the log stays the same after later edits, renames,
and merges, with or without Git. The creation year determines the
document's directory. The closure year determines its log page.

A reopened work item goes back to its active list. Set a new closure date
when closing it again. Switching between final statuses leaves the date
as recorded.

Changes to the title, result, or path update the row on the same year's
page. The generator rebases relative links in the result from each index
page, preserving their targets and anchors. It copies external addresses,
absolute links, and code examples verbatim and leaves the source document
untouched.

## 3. File ownership <a id="ownership"></a>

A generated file starts with this marker.

```html
<!-- lipi:generated:workflow-index -->
```

The marker applies only to the exact paths in the index file table. All
other files in `index/` remain project files. A project file already at
a new output path stops regeneration before any writes. Symbolic links at
participating index paths also stop regeneration.

Regeneration replaces manual edits to generated indexes. It writes a file
only when the bytes change. Commit the index with the workflow documents.
The generator leaves the Git index alone.

## 4. Regenerate and check <a id="refresh"></a>

After changing a workflow document header, run:

```bash
lipi index
```

The command builds the full set, verifies the paths and file ownership,
then writes changes. A write failure or interruption rolls back file
writes and newly created directories.

A local `lipi check` regenerates outdated files automatically. In CI or
with `--staged`, `--diff`, or `--format github`, it reports each outdated
file separately as [W7](codes.md#w7). An explicit `lipi index` regenerates
the set in those environments as well.

After successful regeneration, checks use the new pages to verify links
and the graph. Creating and collecting workflow documents uses the same
set, so the lists and closure log need no separate maintenance.

## 5. Organize documents by year <a id="upgrade"></a>

If documents already follow the [lipi workflow rules](rules.md#workflow)
and sit directly in their type directories, `lipi init` moves them into
creation-year directories and applies the rules as one operation. Preview
the plan and run it from the Git repository root.

```bash
lipi init --dry-run
lipi init
lipi check
```

The plan shows the old and new paths and changes to rules, state, and
indexes. PLN, ISS, DSC, and AUD move into the year from `Created`. A
document directory moves with all its attachments. Document IDs stay the
same. ADR, `.agents/lipi-feedback/`, and archives stay in place. Both an
initial setup and a subsequent update can move documents that already
follow the format. Use [`lipi migrate`](commands.md#migrate) to import
documents in another format.

When at least one document is actually moved into a year directory,
the conversion fills in missing `Closed` dates on final documents. If all
documents already use year directories, fix missing dates in their
headers. The date comes from the commit that last closed the document.
The conversion recognizes the former Russian `Статус` field in historical
commits. If the file has no Git history, it uses
`Updated`. If history exists and HEAD does not confirm the final status,
init reports an error. Each `Closed date` line in the plan shows the
document's original path, the date, and its source. For a date from Git,
the source includes the closing commit hash. The [UTC limit](#closure)
applies both to recorded and calculated dates. A valid existing date is
kept on subsequent runs. Unreadable or ambiguous history stops the
operation.

The command validates the entire plan before writing. It reports the
path and reason for each of these conditions.

- Workflow directory outside the project, flat documents outside a Git
  repository, or a conversion started outside the repository root.
- Invalid header dates, a duplicate ID, an ambiguous layout, or a year
  that differs from `Created`. Resolve the year mismatch with `lipi mv` first.
- Uncommitted changes to affected files, a Git conflict, an occupied
  destination, a project file at a new index path, or a symbolic link.
- Invalid baseline or review state, or a change to a reviewed region that
  cannot preserve the confirmation through a path rewrite.

Refusals occur before the lock file is updated. On a write failure or
interruption, the shared plan rolls back moves, files, permissions,
directories, and the Git index. Rules, the hook, headers, the baseline,
active review marks, and the full index set apply together. The move
rewrites baseline addresses and addresses of confirmed, movable A4 pairs
without accepting new debt or reconfirming content. Check codes,
occurrence counts, and the other details of findings remain intact.
Unrelated changes and already staged files remain intact as well. Git
shows the moves. Review and stage other changes explicitly. If an external
edit occurs during rollback, the command keeps it and reports the
incomplete rollback.

The project scaffold can use year directories without Git. Documents
already organized by year stay in place. Check the `lipi check` findings
for any header corrections.

When a baseline is being created for the first time, the dry run shows
its file. Project commands that measure debt run only when the plan is
applied.
