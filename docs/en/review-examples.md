# A4 review examples

See the [review reference](review.md) for commands and rules. These
examples use synthetic data.

## One trace pair <a id="trace"></a>

In this example, `src/retry.py` has exactly three lines, each ending in LF.

```python
# @trace docs/api.md#retry
def retry_limit():
    return 3
```

The region at `docs/api.md#retry` has exactly these three LF-terminated
lines.

```markdown
## Retry <a id="retry"></a>

Allow at most three attempts.
```

Suppose the change that moves the limit into a function is newer than
the documentation and raises A4. Preview the pair.

```text
lipi review docs/api.md#retry --at src/retry.py:1 --full
```

The command shows A4, both regions, their coordinates, and fingerprints.
The state digests below come from these lines. The registry records
the example repository's HEAD and the review timestamp. Use the token from the actual preview. It also
accounts for settings and the previous review registry. After reading
both regions, confirm the review.

```text
lipi review docs/api.md#retry --at src/retry.py:1 --full --confirm <token-from-preview> --by agent:codex --reason "The limit moved into a function. The number of attempts and the documentation are unchanged."
```

Replace the angle-bracketed placeholder with the token. A successful
write exits with 0 and updates `.agents/lipi/reviews.json`.

```json
{
  "algorithm": "sha256-lines-v1",
  "entries": [
    {
      "head": "249f960ac80fcc97ed69e7a9f4308d77263a146c",
      "id": "b4ec86ecd89f4883b7e9f6cd4c38e7a48865f9101f08697917c769d9128f1642",
      "reason": "The limit moved into a function. The number of attempts and the documentation are unchanged.",
      "relation": "trace",
      "reviewed_at": "2026-11-19T08:33:17Z",
      "reviewer": "agent:codex",
      "source": {
        "kind": "trace",
        "path": "src/retry.py",
        "sha256": "75e47a6d98b5d79190a142229fc4d1dcb334736017dfad523b1418cc2b302862"
      },
      "target": {
        "anchor": "retry",
        "kind": "anchor",
        "path": "docs/api.md",
        "sha256": "cf933c0c262505db9b4314cede51e63e4c60525a6a60c9f55b8501993d536a70"
      }
    }
  ],
  "schema": 1
}
```

Previewing the pair again reports its existing ID. Confirming a new
token returns `result: "unchanged"` and preserves the reviewer and date
of the first review. Changing `return 3` to `return 4` invalidates the
mark. An unrelated commit or inserting lines before the region leaves
it valid. Commit the file explicitly.

## Refusal without writing <a id="refusal"></a>

Suppose one file has two trace marker groups targeting
`docs/api.md#retry`. Selecting the file without a line number returns
`error: "ambiguous"`, exits with 2, and lists both regions even if only
one currently raises A4. Add `--at src/retry.py:1` to pick the first
group. If normalized groups are byte-identical, a line number cannot
distinguish them in saved state: the preview itself already answers
`ambiguous`, even with a line number, and no confirmation is possible.

Changing a region between preview and confirmation gives this response.

```json
{
  "schema": 1,
  "operation": "review",
  "error": "changed-preview",
  "message": "state changed after the preview. Get a new preview"
}
```

The command exits with 2 and leaves the registry bytes unchanged.
T1, T2, T3, an absent A4, or a disabled check cannot be confirmed.
Corrupt review registry JSON raises C1 and prevents confirmation
for all regions.

## Managed move <a id="move"></a>

For the example pair, `lipi mv docs/api.md docs/http.md` rewrites the
target path and the trace marker line in `src/retry.py`. The source
file stays in place and its fingerprint changes because the trace
marker address changed. The target gets a new path and keeps its
fingerprint if its region text stays the same. The command calculates
a new ID and preserves the reviewer and review details.

If moving the page rewrites relative links within the target region,
its fingerprint changes too. Only the exact mechanical edits in the
plan preserve the review. After a manual `git mv`, the registry entry
keeps its old addresses and stops matching.

## Prune review marks <a id="prune"></a>

After the code changes, the old review mark stops matching. For the
same example, run:

```text
lipi review --prune --format json
lipi review --prune --confirm <token-from-preview> --format json
```

The first command lists the pair with reason `changed`. The second
removes only the listed entries. The preview leaves the registry
untouched. After the only stale entry is removed, the response has
this shape.

```json
{"schema": 1, "operation": "prune", "result": "written", "file": ".agents/lipi/reviews.json", "removed": 1, "remaining": 0, "unchecked": 0}
```

The file remains with an empty `entries` array. Ambiguous and
unverifiable entries are kept and listed separately.
