# Find a document by its text

## From a question to a slice <a id="command"></a>

If you know a section address, open it with `lipi slice`. If a question misses
the [ordinary target search](slice.md#target), run the suggested `--search`
command to look for the same words in headings and paragraphs.

```bash
lipi slice 'How long do we keep a copy?'
lipi slice --search 'How long do we keep a copy?'
lipi slice docs/storage.md#cleanup
```

For example, the heading might be “Cleanup policy” and the matching sentence
might read “We keep a copy for 30 days.” Read the excerpt before opening the
section. Even a single candidate can be about a different kind of copy.

## Where to search <a id="scope"></a>

A query without a prefix searches eligible Markdown pages in the current
repository. To search one direct connection, use its configured name:

```bash
lipi slice --search 'library::How long do we keep a copy?'
```

The connection’s [read scopes and page directories](settings.md#repos)
determine which pages it can search. A neighbor needs its own `lipi.json`
for text search. Local results can suggest the same query in a neighbor
even when there are local matches. Each command searches only the
repository you select.

## How matches are ranked <a id="match"></a>

Words match regardless of case. Short terms such as `API` match as whole
words. Longer words can match with a one-letter change at the end when they
share at least four initial letters. This finds `report` for `reports`.
For `copies` and `copy`, try the other spelling.

Search weighs each distinct query word by how common it is among pages with
at least one match. Several words in one paragraph can together outweigh a
single rare word. A distinctive term such as `API` can still outweigh several
words shared by most matching pages. Repeating a word on a page gives it no
extra weight. A match still counts in a one-page repository. Exact matches
rank higher when other evidence is equal. Each target appears once with its best excerpt.

## Read or open a result <a id="output"></a>

The list shows up to five candidates and the total found. Use the target to
open a slice, or open `file:line` in your editor to jump to the matching
words. An excerpt outside an explicit anchor leads to the page itself.

For tools, add `--format json`. The schema 1 response has `query`, `total`
and `candidates` in display order. Here is one candidate:

```json
{"repo":null,"target":"docs/storage.md#cleanup","title":"Cleanup policy","excerpt":"We keep a copy for 30 days.","file":"docs/storage.md","line":12}
```

For a neighbor, prefix `target` with `repo::` to open it. The editor path
is relative to the directory where you ran Lipi, or absolute across drives
on Windows. Lines start at 1. The same file and line can be opened from a
subdirectory using the path printed there.

After a textual target miss, JSON provides the command in `search_command`.
An explicit local search can also return `suggestions` for connected
repositories. With a readable source, exit code 0 means at least one
candidate and 1 means no matches. An unavailable connection returns 0 with
`incomplete: true`. Invalid arguments or settings return 2.
