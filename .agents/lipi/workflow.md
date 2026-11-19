# Workflow documents

Plans, issues, discussions, decisions, and audits record what was known at
the time. Use the [documentation](../../docs/en/README.md) for the project's
current behavior. Create a workflow document when the work calls for one.
For a routine task, make the change, verify it, and report the result.

## Types and directories <a id="types"></a>

| Type | Prefix | Directory | Contents | Statuses |
| --- | --- | --- | --- | --- |
| Plan | `pln` | `plan/YYYY/` | purpose, approach, steps, completion criteria | new, in progress, pending acceptance, deferred, completed, canceled |
| Issue | `iss` | `issue/YYYY/` | bug, friction, request, or question with an observation and its location | open, in progress, closed |
| Discussion | `dsc` | `discussion/YYYY/` | question and options without a commitment to implement | open, closed |
| Decision | `adr` | `adr/` | context, decision, consequences | proposed, accepted, superseded, rejected |
| Audit | `aud` | `audit/YYYY/` | question, facts, findings, conclusions | none |

The directory is determined by document type. Keep the file in place when
its status changes so existing links still work. For plans, issues,
discussions, and audits, the year directory must match `Created`. ADRs
and feedback stay in flat directories. An incorrect layout gives W10.
A mismatched year gives W11 with a hint for `lipi mv`.

Set the decision directory via `decisions` in `lipi.json`. It defaults to
`adr/` within the workflow directory. Decision headers, links, and anchors
are checked even if the directory is inside documentation. D3 and D4
skip these decisions.

## Names and numbers <a id="naming"></a>

- A name such as `pln-001-short-name.md` consists of a prefix, a number of
  at least three digits, and a hyphenated name in Latin letters.
- Each prefix has its own sequence across years and the archive. A number
  stays with its document and is never reused.
- Decisions allow `001-….md`, `0001-….md`, and `adr-001-….md`. All three give
  the canonical ID `ADR-001`. Two files with the same ID are an error.
  If existing decisions omit the prefix, new decisions also omit it and
  take the largest width among names without the prefix: after
  `0001-existing.md` and `adr-00002-existing.md` comes `0003-new-decision.md`.
- When creating an ADR, archived names reserve their numbers. Names
  beginning with `adr-NNN-` count anywhere in the workflow directory
  and in the project's root `history/`. Bare numbers count in `adr`
  directories, directories named like the configured decision directory,
  or its `history/`. Keep such a directory or the prefix when archiving.
  The naming convention for active files takes precedence. If there
  are none, use the archived names.
- For a document with attachments, use a folder such as `aud-001-topic/`
  with `aud-001-readme.md` as its main file. Put attachments in that folder.
- Use `lipi new` to create a document and assign the next number:

```bash
lipi new pln "Plan title"
lipi new iss "What broke" bug
```

## Header <a id="header"></a>

Write field names, status and kind values, and required headings in
English. The title, body, and `Result` value can use the project's
language. The header follows the first-level heading:

```text
- Created: YYYY-MM-DD
- Updated: YYYY-MM-DD
- Status: one value from the table
- Closed: YYYY-MM-DD (for a final status)
- Result: the outcome in one sentence
```

- **Status** holds exactly one value without an explanation. Record the
  status only in this field.
- **Result** is required for a completed or canceled plan and a closed
  issue. The log uses it.
- **Closed** is required for completed or canceled plans, closed issues
  or discussions, and superseded or rejected decisions. A missing date
  gives W4. An invalid date, one earlier than `Created`, or one later
  than the current UTC date plus one day gives W3. Set the date when
  closing the item. Keep it on later edits. If you reopen and close the
  item again, set a new date. An audit needs no closing date.
- An issue's `Kind` is one of `bug`, `friction`, `request`, or `question`.
  Set `Recipient: lipi` to address an issue to lipi for collection.
- A plan or issue may have `- Due: YYYY-MM-DD`. A8 warns of an overdue
  or invalid date on unfinished work. The due date itself still counts
  as on time. Items without a due date and items with final or unknown
  statuses are skipped. Set the check's level through `codes`.
- A decision that refines another contains `- Refines: [ADR-NNN](path.md)`
  and may repeat the field. The original decision remains `accepted`.
  The slice shows related accepted decisions under `Rules and decisions
  to follow`. Ordinary links between decisions provide context. Projects translate other
  status formats into this header.
- **Required sections** are `Observation` for open or in-progress issues,
  and `Purpose` and `Completion criteria` for plans in progress or pending
  acceptance. A missing or empty required section gives W8.

## Issues <a id="issue"></a>

After `lipi new iss`, review any suggestions for similar open issues.
The suggestions are based on overlapping words. Read the issues to check
for duplicates.

File an issue for anything that will take further work: a defect, a point
of friction, a user request, or an open question. Keep each issue to one
file and a few lines. When you take it on, set `in progress` and link to
a plan if needed. When closing it, set `closed` and record the outcome,
such as a fix, rejection, or the ID of the issue it duplicates.

## Discussions <a id="discussion"></a>

If an accepted decision links to an open discussion, A7 asks whether the
discussion can close. The decision may address only some questions. Review
the status yourself. Set the check's level through `codes`.

A discussion records the question, options, and conclusion at the time.
Add to it while it is open. Once closed, preserve the body and result as
a record of that date. `lipi mv` may update paths while keeping the text
and meaning intact. If the conclusion is out of date or inaccurate,
open a new discussion or decision and link to the earlier one. Record
the decisions that apply in the decision directory (`adr`).

## Index and log <a id="index"></a>

The checker builds [INDEX.md](../../workflow/INDEX.md) from document
headers with work in progress, work pending acceptance, counts, and links.
Full lists are under `index/`:

- `plans.md` lists plans with a non-final status.
- `issues.md` lists open and in-progress issues.
- `discussions.md` lists open discussions.
- `decisions.md` lists proposed and accepted decisions.
- `audits.md` lists all audits.

The log in `index/done/YYYY.md` lists completed and canceled plans,
closed issues and discussions, and superseded and rejected decisions.
The `Closed` field alone determines the year. Keep it unchanged on
later edits. Reopening the item returns it to the active list. Set a
new date if you close it again. The generator leaves headers intact
and derives dates only from them. It writes the index set only when
all required dates are valid.

Regenerate indexes with `lipi index` after changing a header. Keep
empty lists and already generated year pages. Do not edit indexes by
hand. The marker `<!-- lipi:generated:workflow-index -->` must be the
first line of the file, with nothing before it, and allows regeneration
at the exact index path. A user file or symlink at that path stops regeneration.

## Master plan <a id="masterplan"></a>

[masterplan.md](../../workflow/masterplan.md) shows what comes next
and in which order. It lists upcoming work, one line per work item,
with a link to its plan or issue and any dependencies.

- Add work only when the user has agreed to do it and placed it in the
  queue. Add it in that same commit. Let the user decide the order.
- Keep statuses, results, check counts, and history in the work items
  and index.
- Remove completed work. The checker flags it if it stays in the master plan.
- Keep the master plan within its size limit. Move details into plans.

## Archive <a id="history"></a>

`history/` holds material that no longer participates in current work.
The checker and normal searches skip it. If you consult the archive for
context, verify any claims against the current code and documentation.

## Links <a id="links"></a>

Use relative links between workflow documents. Link to documentation
and code where they already explain something. Rerun checks when the
code changes.
