# Move pages and directories

`lipi mv` moves project files in Git and updates references to them.
For a nested project, the nearest `lipi.json` above the current directory
defines the project root. Without one, the Git root is used. The plan
covers only files within the project. Moving a page preserves its
anchors and content. Splitting a page and distributing its anchors are
edits for the author to make.

## Command forms and paths <a id="paths"></a>

```bash
lipi mv docs/old.md docs/reference/new.md
lipi mv docs docs/ru
lipi mv --from moves.txt
```

Without `--apply`, the command shows the complete plan without writing
files. Repeat the same invocation with `--apply` to carry it out. Run
`lipi help mv` for help.

Positional paths, including the list file passed to `--from`, are relative
to the current directory. Paths **in the list** are relative to the Git
root. Each line contains exactly two whitespace-separated paths. Quoting
and escapes follow shell rules. The parser performs no command
execution, variable substitution, or glob expansion. Blank lines and
unquoted `#` comments are skipped, while a quoted `#` is part of the
path. Because the list is an explicit command input, the command reads
it regardless of Git filtering.

```text
# Paths from the Git repository root
"docs/old page.md" "docs/reference/page.md"
docs/guide docs/ru/guide
docs/logo.svg assets/logo.svg
```

The plan also shows [review marks to move](#reviews) in the project state.

## What moves <a id="scope"></a>

A single positional file must be a Git-tracked Markdown page. A directory
expands into its eligible tracked files, preserving the layout. Images
and other assets move whether or not they have incoming links. A
`--from` list can contain directories and individual tracked files,
including images.

A directory can move inside itself, as in `docs → docs/ru`. The command
fixes the set of source files before calculating the new paths, so it
does not scan the destination as another source.

Untracked files and files in excluded areas stay in place. The report
lists them except for files ignored by Git. The exclusions include
`skip_dirs`, internal directories, lipi-managed files, `history/`,
and connected repositories. The report mentions the archive only when present.
The command neither moves symbolic links nor follows them outside the
project. A `skip_dirs` entry without a slash excludes a directory name
at any depth. An entry containing `/` is relative to the project root.
Incoming references follow the [shared file selection rules](checking.md),
which skip Git-ignored files. A new, nonignored file with a reference is
part of the plan, and directory and list moves still require
[clean affected files](#plan).

## Update references <a id="links"></a>

The command builds one mapping between source and destination addresses
and parses each project file for references once. For every link, it
calculates the new location of both the linking page and its target.
Ignored paths stay out of the plan even when referenced by a moving page.

- Incoming Markdown links from documentation, workflow documents, and
  project agent instructions get their targets updated. This includes images and HTML `img[src]` and `a[href]`.
  Only the address changes. Code examples and HTML comments are skipped.
- Relative links between files that move together keep working as written.
- The command rebases links from a moving page to a page outside the move.
  For instance, `../README.md` in `docs/page.md` becomes `../../README.md`
  after `docs → docs/ru`.
- `@trace` and `covers` paths are root-relative and change even within a
  moving directory. Lines with `lipi: ignore-trace` stay as examples and
  are omitted from the connected repository trace marker report. Work
  item IDs and external targets of the form `name::target` stay as written.
- Update Markdown code examples, string literals, and arbitrary paths
  in build settings by hand.

Only reference addresses change in closed discussions. Connected
repositories with `code` or `tests` access remain untouched. The report
lists the pages and the number of lines with trace markers to update
there. The command can detect only known external references.

## Validate the plan <a id="plan"></a>

The plan lists all moves, exact replacements by file and line, and
skipped items. Before any write, the command rejects:

- Missing, untracked, or ineligible sources.
- Duplicate sources, overlapping source directories, or a file included
  separately and through its directory.
- Identical source and destination, multiple moves to one destination,
  or a destination file and directory conflict.
- Occupied destinations, including tracked files deleted from the
  working tree. Chains and swaps of occupied paths are rejected.
- Paths outside the project, excluded areas, or symbolic links.
- A Git conflict, inability to write, or a change to an affected file or
  the index after the plan was prepared.

For a directory move or `--from` list, every affected file must match
its committed state in both the working tree and the index. This
includes files being moved and files with references to update. The
command refuses the move and lists any affected files that differ.
The same rule applies to a list containing one pair. Unaffected files
can have local changes, including staged changes.

Cleanliness is determined by file contents and mode after accounting
for Git transformations for the path, including line endings. Changes
only to filesystem metadata after a rollback do not make a file dirty,
including binary files. The check leaves the real Git index untouched.

A positional move of one Markdown page preserves local edits to the
page and files that link to it.

The plan also validates the [review registry](#reviews). A corrupt
registry raises C1. The operation stops before writing if an affected
valid review mark cannot be preserved. Obsolete and unchecked entries
stay in the registry.

## Review marks <a id="reviews"></a>

The same plan moves valid A4 review marks in
`.agents/lipi/reviews.json`. It updates paths, fingerprints for exact
address replacements, and IDs, while preserving the reviewer, date,
and reason. The rule applies to replacements in files that stay in
place as well. Stale entries remain unconfirmed. A corrupt registry
raises C1. If the active review mark cannot be proven to survive the
move, the command refuses to write. The rollback includes the registry.
See the [review move rules](review.md#move).

## Apply and roll back <a id="apply"></a>

The command checks all affected files before applying the plan. It may
reread a file to see if it changed, using the references it already
parsed. On application failure or a caught interruption, including
`Ctrl+C`, a bulk move restores paths, file contents, and the Git index
to their original state. Unaffected user changes survive both a
successful move and a rollback.

A forced process kill or power loss can interrupt rollback. If the
command cannot restore the original state, it reports the incomplete
rollback.

After applying a plan, review `git diff` and `git diff --cached`. Moves
are staged and replacements of references are left in the working
tree. Run `lipi check` and stage the complete result.

Exit code **0** means the plan or move succeeded, **2** means an invalid
invocation or refusal, and **130** means the command caught an interruption.
