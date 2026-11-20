# Use Lipi on one task in an existing project

Suppose a screen lists records and you want it to open a saved revision.
Does the service already read a revision by ID? Start with that question.
One documented contract, its implementation, and a test are enough to begin.

## Find the contract <a id="find"></a>

Start in the directory that contains the project's code and documentation.
Keep generated data such as `exports/` out of scans with `.gitignore` if it is
untracked, or with [`skip_dirs`](settings.md#skip-dirs) for tracked data or projects without Git.
For a package that keeps its documentation in `docs/`, preview the setup,
then apply it using the same options.

```bash
lipi init --docs docs --dry-run
lipi init --docs docs
lipi check
lipi map
```

If the project keeps its own backlog, it can set `"workflow": null` in
`lipi.json`. On first setup, `lipi check --no-baseline` also shows
pre-existing errors recorded in the baseline. [Setup details](../../SETUP.md#init).

Look for the operation on the map, or try a short phrase from a page or
section title, such as `lipi slice 'read a saved revision'`. An exact
address such as `lipi slice 'docs/records.md#read-revision'` goes straight
to that section. Open the implementation and the client it leads to.
If the service already accepts a revision ID and the screen still calls
the list operation, you have found where to start the change.

## Link the behavior <a id="mark"></a>

In `docs/records.md`, give the promise its own anchor. Link the page from
the documentation index if it is new.

```markdown
## Read a saved revision <a id="read-revision"></a>

Reading a revision by ID returns the label stored in that revision.
```

Put `# @trace docs/records.md#read-revision` above the function that forms
the response and above the test that checks its label. Use the comment
syntax of the source language. Mark the client function that reads this
response with the same target. If it lives in another repository, qualify
the target as shown below.

## Work across two repositories <a id="repos"></a>

Suppose `service/` and `client/` are neighboring clones, each with its own
`lipi.json`. Merge these settings into the existing files.

**In `client/lipi.json`**, connect to the repository that owns the contract.

```json
{"repos": {"service": {"path": "../service", "read": ["docs"]}}}
```

The client reader can now use `@trace service::docs/records.md#read-revision`.
From `client/`, run `lipi slice 'service::docs/records.md#read-revision'`.

**In `service/lipi.json`**, add the reverse connection to see the consumer
while reviewing a service change.

```json
{"repos": {"client": {"path": "../client", "read": ["code", "tests"]}}}
```

From `service/`, run `lipi slice 'docs/records.md#read-revision'`. Look for
the reader under `client::`. The summary identifies which sources Lipi could
read. Staleness checks cover local links. Review the connected reader when
the response changes. [Connection settings](settings.md#repos).

## Review the change <a id="review"></a>

Suppose the response builder is also marked for `docs/records.md#display`,
a broader section about displaying records. The client screen and an export
preview both use that section. After editing the tracked response builder,
run `lipi slice --diff HEAD` in `service/`. With these markers the location
labels tell you why each client file appeared.

| Client location | Label | What to inspect |
| --- | --- | --- |
| Revision reader | `via #read-revision` | Can it read the changed response? |
| Record screen | `via #display` | What does the user see? |
| Export preview | `via #display` | Does this separate display path use the changed field? |

A shared marker explains the link. Open the code to establish which path
actually calls the operation. A reader can accept a new optional field
while the screen continues to show only the old fields. [Diff slices](slice-diff.md#response).

For a test of revision selection, make revision B current, give A and B
different labels, and request A. Assert that the returned label is A's.
An assertion on an echoed request ID would also pass if the service returned
B's content. Run the test if your conclusion depends on this behavior.

If you later need to find Markdown pages outside a neighbor's documentation
directory, add [`page_dirs`](settings.md#repos) to that connection and
[search by title](slice-output.md#repo-search).
