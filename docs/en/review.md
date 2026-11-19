# Review a staleness warning

`lipi review` records a review of one A4 pair. See
[examples](review-examples.md) and the [command reference](commands.md).

## Pairs and regions <a id="pair"></a>

Only local links eligible for A4 can be reviewed.

| `relation` | `source` | `target` |
| --- | --- | --- |
| `trace` | Trace region in a code or test file | Explicit Markdown anchor |

A review mark applies to A4 for an `@trace` link to a local Markdown
anchor. Pair selection follows the shared file scan and target
resolution rules.

A trace marker group is the longest run of adjacent physical lines
with active stand-alone trace markers. A line with code and a trace
marker forms its own group. Several markers on one line make one
group and repeated targets make one edge. An unresolved active marker
still forms a boundary. `ignore-trace` does not. The trace region
includes the group and the text up to the next group or EOF.
Dating the code for A4 skips initial stand-alone trace marker comments
and counts code alongside an inline marker. Fingerprints include
every line in the region.

Markdown uses the shared anchor region. A table region includes its
header and selected row, excluding rows between them.

## Working tree <a id="worktree"></a>

Applying review marks uses the registry and both regions from the
working tree. `audit --reviews-since` separately reads the earlier
registry from Git. Review marks do not affect T2. `review --staged`
and `review --diff` are unsupported. `slice --staged` and `slice --diff`
select targets using Git and compute A4 from the working tree. Git
history is required to confirm A4.

## Fingerprints and identity <a id="fingerprints"></a>

The `sha256-lines-v1` algorithm works as follows.

1. Read as UTF-8 and replace CRLF and lone CR with LF. Split on LF
   and keep the ending LF in its line. Omit the empty element after a
   final LF. Other Unicode line separators remain ordinary characters.
2. Select the exact ordered lines in the region. Ignore absolute line
   numbers and gaps between disjoint parts. Keep whitespace, comments,
   trace markers, blank lines, and the final newline if present.
3. Hash the canonical JSON array `["sha256-lines-v1", kind, lines]`
   encoded as UTF-8, with `kind` set to `trace` or `anchor`.

Canonical JSON here uses ascending object keys, no spaces between
elements, Unicode directly in UTF-8, and standard escaping of control
characters, `"`, and `\`. The `/` character stays unescaped. The standard
library equivalent is
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)`.
Unpaired surrogates are invalid. SHA-256 hashes are 64 lowercase hex
digits.

The entry `id` is the SHA-256 of the canonical array
`["review-pair-v1", relation, source, target]`. Both descriptors include
their fingerprints. The reviewer, timestamp, HEAD, and coordinates
are excluded. This ID identifies a pair in a particular state.

For a trace marker, the command looks in the selected file for every
group with the required active edge and source fingerprint. Exactly
one must match. The target must also resolve uniquely and have the
expected fingerprint. Identical groups block creation and application
of the mark. A line number cannot resolve that ambiguity in saved state.

Changes to line numbers outside the regions and unrelated commits
preserve a mark. A unique unchanged group moved within its file still
matches. The lookup does not use cross-file moves, similar text, or
symbols. Removing or changing the link or anchor invalidates the mark.
A lipi-managed move can preserve it as described below. A manual
rename invalidates it. An exact reversal can restore it before pruning.
The registry can hold several versions of a pair. Stale versions
appear in the prune preview.

## `.agents/lipi/reviews.json` <a id="state"></a>

Required top-level fields are `schema: 1`,
`algorithm: "sha256-lines-v1"`, and `entries`, which may be an empty array.

| Entry field | Type and value |
| --- | --- |
| `id` | Pair hash computed above |
| `relation` | `trace` |
| `source`, `target` | Descriptors for the two sides, shown below |
| `reviewer` | Nonempty string explicitly passed via `--by` |
| `reviewed_at` | Valid UTC timestamp at write time, `YYYY-MM-DDTHH:MM:SSZ` |
| `reason` | Nonempty string explaining the result of the review |
| `head` | HEAD at review time, a full Git OID of 40 or 64 lowercase hex digits, or null |

A trace descriptor is `{"kind":"trace","path":"src/a.py","sha256":"…"}`.
An anchor descriptor is `{"kind":"anchor","path":"docs/a.md","anchor":"rule","sha256":"…"}`.
The ellipses stand for actual hashes. See the
[example registry](review-examples.md#trace) for a complete value.
Line numbers, ordinals, and symbols are omitted. Source kind is
always `trace` and target kind is `anchor`. Keeping `relation` allows
schema 1 to be extended. Other values raise C1. Explain why the
documentation is still accurate. The command checks that the reason
and reviewer are nonempty after trimming surrounding whitespace.

Paths are canonical project-relative POSIX file paths. A leading `/`,
drive prefix, `\`, NUL, empty segments, `.`, and `..` are invalid.
The anchor is the exact ID without `#`. HEAD is informational and
does not affect matching or establish reproducibility for the whole
tree. The schema has no index snapshots or line ranges.

Invalid JSON or UTF-8, duplicate JSON keys, unknown fields, invalid
version, algorithm, or relation, incorrect types (including a Boolean
schema), mismatched descriptor kinds, invalid path, hash, ID, date, or
OID, empty reviewer or reason, duplicate IDs, or an unreadable existing
file all raise C1 and exit with 2. Validation covers the whole file.
A missing region or changed fingerprint is a state mismatch and does
not corrupt the entry.

A missing file is an empty registry. The file is absent from
`lipi.lock.files` and survives init. The write command creates it when
needed. It uses UTF-8, LF, two-space indentation, sorted keys and
entries sorted by ID, and a final LF. Reconfirming the exact same pair
is a no-op and preserves the reviewer, timestamp, and reason.

## Select and confirm <a id="confirm"></a>

Preview and refusal text follow the interface language. See [Review JSON](#json) for machine responses.

```text
lipi review TARGET --at PATH[:LINE] [--full] [--format json]
```

TARGET is an exact local `path#anchor`. `--at` selects a code group by
project-relative path and an optional positive line number within it.
The suffix after the last `:` is the line number. The command supports
exact selection of one pair. Word searches, wildcards, entire files,
and all pairs for a target are unsupported.

Pair selection uses the structural graph before staleness filtering.
Two groups in one file targeting the same anchor are ambiguous even
if only one currently raises A4. The response lists the paths,
coordinates, and targets without writing. A line number selects one
group, except when the groups have identical saved identities.

The selected pair must raise A4 before review marks are applied.
You may select an already reviewed pair. A disabled code has no
candidates.

The first invocation previews the code, level, relation, both sides,
exact ranges, the first 20 selected lines on each side, omitted line
counts, fingerprints, HEAD, any existing mark, and a token. `--full`
shows all selected lines and gives the same token. Supply the reason
when confirming.

Confirm by repeating the command with:

```text
--confirm TOKEN --by ACTOR --reason TEXT
```

The second invocation rereads the working tree, selects the pair, and
checks the token. Selected files and regions and the registry must
match the preview. The opaque SHA-256 token binds the pair, HEAD,
both regions' contents, settings used for selection, and the registry
bytes. A missing registry and a valid registry with an empty `entries` array give
different tokens.
Nonempty `--by` and `--reason` are required. The command has no
interactive confirmation or global `--yes` and reads no reviewer from
`git config`.

A concurrent change returns `changed-preview` with exit code 2 and no
write. Get a new preview. The command checks that its file reads are
stable. Registry writes are serialized and use atomic replacement
after comparing the previous bytes. The project tree remains unlocked.
A later edit to either side invalidates the recorded state. Check,
audit, and slice leave the registry alone and preserve existing index
update behavior.

A successful preview, write, or no-op exits with 0. Invalid arguments,
no candidate, ambiguity, C1, a write error, or a changed preview exits
with 2. Text and JSON report the same result.

## Review JSON <a id="json"></a>

Lipi writes `message` in English in JSON. Excerpts, reviewer names, and reasons keep their original language.

| Operation | Fields in addition to `schema: 1` and `operation: "review"` |
| --- | --- |
| Preview | `result:"preview"`, `pair` (id, relation, source, target), `code`, `level`, `source_view`, `target_view`, `head`, `existing` (id or null), `token` |
| Write or no-op | `result:"written"` or `"unchanged"`, `file`, `entry` (complete entry) |
| Refusal | `error`, `message`, and `candidates` for ambiguity |

A view contains `ranges:[[first,last],…]`, `lines:["raw line\n",…]`, and
`omitted:N`. Ranges describe the full region and are informational.
The lines array contains up to 20 selected lines, or all selected lines
with `--full`. A
candidate has `relation`, `source`, `target`, `source_ranges`, and
`target_ranges`. If separate groups share an ID, ranges distinguish
the candidates. `level` is exactly `error` or `warning` after applying
check level settings.

`invalid-arguments`, `no-candidate`, `ambiguous`, `unavailable`,
`changed-preview`, and `write-failed` use this shape and exit with 2.
C1 uses the checker's JSON shape with `errors:[{"code":"C1",…}]`. Errors
and previews leave the registry untouched. See the [JSON examples](review-examples.md).

## Apply marks and report totals <a id="summary"></a>

The command validates the whole registry before checks. For each
verified A4 pair, it checks both fingerprints and the edge and removes
only matching candidates. It then creates findings and applies levels
and the baseline. Disabled codes do not count as suppressed. Marks
apply at level `error` and with `--strict` or `--no-baseline`. The
`--structure` link graph and T2 chains stay the same.

Without the file, check, audit, and slice keep the usual fields. If
the file exists, `summary` adds:

| Field | Commands | Meaning |
| --- | --- | --- |
| `reviewed_pairs` | check, audit, slice | Unique pairs whose marks suppressed an active A4 in this result |
| `reviewed_obsolete` | audit | Confirmed stale entries across the current tree |
| `reviewed_unchecked` | audit | Entries whose state could not be determined |
| `reviewed_by` | audit | Reviewers, count, and latest mark for applied pairs |

Each pair counts once. Other code locations with the same target are
considered separately. Ordinary check runs no A4, so the counter is
zero. Its T2 check stays as before. Text and GitHub output show separate
informational lines in the selected interface language, including for zero counts. Audit also reports
stale and unchecked marks. These counts are separate from findings
and annotations and cannot cause exit code 1. Existing error and
warning counts include only remaining findings. The schema stays at 1.

Slice counts reviews across its full selection before applying the
budget or `--only`, after verifying A4. Review marks add no blame calls
above the existing limit and leave `checks.staleness`, checked and total
counts, partial and no-Git status, and `incomplete` unchanged. Applying a
mark requires a verified A4, which requires history. The absence of a
signal alone does not count as a review.

## Reviewers <a id="authors"></a>

`audit --reviews-since <revision>` adds `summary.reviews_since`. It counts
new entries across the registry by reviewer. See the
[fields, boundaries, and examples](checking.md#review-authors).

## Move marks with files <a id="move"></a>

`lipi mv` includes the registry in the move plan. Manual moves leave
it alone. A missing registry stays absent. A corrupt one raises C1
before any write.

An active pair can move if both sides resolve uniquely, both
fingerprints match, and the link exists before the operation.
Current A4 and blame are unnecessary. The plan accounts for paths and
all address changes in both regions, including in files that remain
in place.

The command finds both regions again in the planned tree. Their lines
must exactly match the original selections after the plan's address
replacements, with their order and boundaries intact. Adjacent text
cannot be added and trace marker groups cannot split or merge.
Both sides and the link must still be unique. The command replaces the
entry's paths, affected hashes, and ID while preserving `reviewer`,
`reviewed_at`, `reason`, and `head` from the original review.

The plan shows the old and new IDs, addresses, and changed sides.
The command refuses to write if it cannot prove a transformation for
an affected active pair or finds an ID collision. It lists already
stale and unchecked entries separately and preserves them.

Applying the plan rechecks original bytes and the uniqueness of
regions. Errors and KeyboardInterrupt roll back the registry with
the other affected files. A bulk move requires an affected registry
to match the committed state in the working tree and the index. A
single-page move accepts supported local edits and rolls back to
those bytes. It leaves the registry unstaged. Other rule and content
changes made by init are outside the authorized address replacements.

## Prune review marks <a id="prune"></a>

```text
lipi review --prune [--format json]
lipi review --prune --confirm TOKEN [--format json]
```

The plan covers the full working tree and cannot be combined with a
pair selection, `--full`, `--by`, or `--reason`. It removes only entries
whose link or side is known to be gone or whose prior state no longer
matches any eligible pair. Ambiguity, read errors, configured
exclusions, incomplete scans, and unknown state preserve an entry.
Age, a disabled A4 check, or omission from a slice are insufficient
to establish that a mark is stale. Staleness here is based on the
region.

The preview lists IDs, both sides, and the reason for removal, plus
unchecked entries. Its token binds the whole plan and registry.
Confirmation rechecks the plan and atomically removes exactly the
previewed entries. Empty results leave the file with an empty
`entries` array. If there is no file or nothing to remove, the command
does nothing, does not create or reformat the file, and previews a
null token.

JSON for a preview contains `schema:1`, `operation:"prune"`,
`result:"preview"`, `file`, `basis:"worktree"`, `remove`, `unchecked`,
and `token`. The `remove` and `unchecked` arrays have objects with
`id`, `source`, `target`, and `reason`. Reasons are `changed`,
`missing-source`, `missing-target`, or `missing-relation` for removal,
and `ambiguous`, `unreadable`, or `excluded` for unchecked entries.
Confirmation returns `result:"written"|"unchanged"`, `file`,
`removed:N`, `remaining:M`, and `unchecked:K`. Refusals use the
review error fields and exit codes with `operation:"prune"`. C1 keeps
the checker's shared shape.

Git retains the history of removed entries.
