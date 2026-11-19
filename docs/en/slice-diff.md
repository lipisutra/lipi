# Slice by Git diff

After an edit, `lipi slice` shows the related code locations, decisions, and tests to check. A link is a reason to review the other end. See the [slice contract](slice.md) for blocks, signals, the output budget, and the response schema.

## Selecting changes <a id="selection"></a>

```bash
lipi slice --diff HEAD
lipi slice --diff v1.0.0 --format json
lipi slice --staged
```

Choose exactly one source: a target, `--diff <base>`, or `--staged`. With one Git revision as its base, `--diff` examines both staged and unstaged changes to tracked files in the working tree. Stage untracked files to include them. `--staged` compares the index with HEAD, or with the empty tree before the first commit. Unstaged edits do not affect target selection in this mode.

Reading a diff leaves files and the index untouched and does not run project checks. The code scan excludes Markdown, binary files, oversized files, documentation, workflow and decision directories, and files excluded by the trace marker scan. A pure rename with no line edits adds no targets.

On each side of the diff, a trace group covers the lines up to the next group or the end of the file. Added lines use their new markers. Deleted lines use the old ones, even if the marker or the whole file was removed. Target paths and work item IDs resolve against current project documents. The slice reads links and code locations from the working tree.

## Response <a id="response"></a>

The blocks appear in this order: `signals`, `obey`, `concepts`, `entry`, `code`, `tests`, `context`. Concepts include every resolved target of an affected marker, including pages and work item IDs, with its title and code location count. As in an ordinary slice, these targets supply the applicable accepted decisions, instructions, refinements, and related documents. Code and tests list other locations for the same targets, excluding the changed declarations. A shared concept, decision, or location appears once across all changed files. With `repos`, the diff remains local. The [repository connection rules](slice.md#repos) govern external targets and consumers.

Two notes accompany the summary: a prompt to review related locations, and a count of unmarked changes. An unmarked location is a continuous run of changed lines with no resolved target. For each diff hunk, lipi counts runs on both sides and takes the larger count, so a replacement counts once. An unresolved target does not establish a link.

The summary covers the complete slice before truncation; `checks.diff.unmarked` counts all unmarked runs. A4 and T3 appear as ordinary signals. The presence of a link in the diff alone does not trigger a warning. The staleness check uses current linked locations and the usual [limits](slice.md#staleness). `--only`, `--layer`, `--depth`, `--full`, and the line budget apply as usual. Diff slices have no excerpt. An empty diff or one without trace markers returns 0. Missing Git, an invalid base, or a diff read error returns 2.

A valid [review mark](review.md) suppresses A4 for its pair and keeps the pair in the coverage count. Review marks do not affect T2 checks.

## JSON <a id="json"></a>

The schema version is 1. The target has `kind: "diff"` and a `target` value of `--diff BASE` or `--staged`. Other fields and block items follow the ordinary slice schema, including `repo` and source metadata when connections are configured.

```json
{"checks": {"diff": {"mode": "diff", "base": "HEAD", "files": 2, "unmarked": 1}}}
```

`files` counts affected code files, including renames with no line edits. With `--staged`, `mode` is `staged` and `base` is `null`. Summary notes have codes `diff-review` and `diff-unmarked` and remain visible for all `--only` values. A read error returns `{"schema": 1, "error": "invalid-diff", "message": "Git: fatal: Needed a single revision"}`. Conflicting arguments produce a CLI diagnostic and exit code 2.

See the [diff slice example](slice-examples.md#diff). When `reviews.json` exists, `summary.reviewed_pairs` counts suppressed A4 pairs before truncation and `--only`, as in an [ordinary slice](review.md#summary).
