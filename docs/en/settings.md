# Settings

`lipi.json` lives at the project root. All keys are optional. The checker
validates keys, types, and values against a schema. An unknown key, wrong
type, or invalid value raises C1 and stops the check with exit code 2.
The checker validates the structure of `.agents/lipi/lipi.lock`,
`.agents/lipi/baseline.json`, and [`.agents/lipi/reviews.json`](review.md#state)
when those files exist.

Settings, state, and the baseline have separate files. After initial
creation, edit `lipi.json` by hand. `init` writes `.agents/lipi/lipi.lock`
with the setup version and fingerprints of the rules and CI template.
`lipi baseline` records known project debt in
`.agents/lipi/baseline.json`. `lipi review` writes reviewed A4 pairs to
`.agents/lipi/reviews.json`. Commit these files. When
[moving existing workflow documents](workflow.md#upgrade), paths in the
baseline and active review marks update with the document paths.

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `docs` | string | `docs` | Documentation directory. With `languages`, it must match the directory for the default edition. |
| `description` | string or `null` | unset | System documentation directory when it is separate from end-user help. |
| `workflow` | string or `null` | `workflow` | Workflow document directory. `null` disables its checks and routes lipi feedback to `.agents/lipi-feedback/`. |
| `decisions` | nonempty string | `<workflow>/adr` | Decision directory within the project, with no symlinks in its path when using Git. An explicit value overrides the standard path and works with `"workflow": null`. |
| `repos` | object | unset | Explicit connections to neighboring repositories, with relative `path` and a list of permitted `read` scopes. See [repository connections](#repos). |
| `enforce` | boolean | `false` | Project enforcement mode (ADR-011). `true` uses pre-commit `lipi check --staged` and strict agent instructions. `false` leaves commits unblocked and installs no hook. |
| `languages` | object | unset | Documentation language editions. `default` names the default edition, `editions` maps languages to directories, and `required` lists editions where each page must appear (L1). |
| `release_notes` | string or `null` | unset | Relative path of a release history page, usually `CHANGELOG.md`. D3 skips its size, other documentation checks still apply, and a missing file is allowed. |
| `limits` | object of nonnegative integers | 320 lines and 24 KiB per documentation page, 600 lines per workflow document, 150 lines for the master plan | Size limits: `docs_lines`, `docs_bytes`, `workflow_lines`, `masterplan_lines`. 0 disables a limit. |
| `stale_days` | object of integers | 30, 14, and 60 | Days after which an audit considers a plan, a plan pending acceptance, or an issue stale: `active`, `review`, `issue`. |
| `entry` | array of strings | empty | Regular expressions that match entry-point code lines in audits and slices. |
| `layers` | object mapping path patterns to layers | empty | Map and slice layers. The first match sets the layer, and key order sets display order. An unmatched file uses its top-level directory. |
| `tests` | array of strings | `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`, `*Test.*` | Test filename patterns for maps and slices. The array replaces the built-in patterns. The `tests` layer also identifies tests. |
| `slice_budget` | integer of at least 1 | 60 | Total content lines in a [slice](slice.md#budget). `true`, zero, and negative values are invalid. |
| `skip_dirs` | array of strings | empty | Directories excluded from scans and targets. See [names and paths](#skip-dirs). |
| `checks` | array of objects | empty | Stack-dependent project checks (ADR-008). `name` is the name, `run` is an argument array without a shell, `mode` is `quick` (every check) or `audit` (only with `--audit`), and `timeout` is the time limit in seconds. A failed command raises P1. |
| `codes` | object mapping codes to levels | empty | Project check levels (ADR-012). For each code choose `"error"`, `"warning"`, or `"off"`; the checker's default applies to unspecified codes. Unknown codes or levels raise C1. C1 and V1 are fixed. |

The checker treats documents under `decisions`, such as `"docs/adr"`,
as decisions even when they live inside documentation. It checks their
headers, links, and anchors. D3, D4, and language-pair checks skip them.
Filenames `001-….md`, `0001-….md`, and `adr-001-….md` all resolve to
`ADR-001`. Only the `- Status: …` line in the lipi header sets the status.
Without a workflow directory or an explicit `decisions` key, decisions
are unavailable by ID. `lipi new adr` creates the directory.

The `Created` date determines the year directory for PLN, ISS, DSC, and
AUD. ADR and feedback have no year directories.

The project chooses enforcement with `enforce` (ADR-011), which defaults
to `false`. With `false`, `lipi init` skips hook installation or removes a
previous lipi hook and reports the removal. Agent instructions ask agents
to fix the errors introduced by their changes or report them to the user.
With `"enforce": true`, `lipi init` installs a pre-commit hook that runs
`lipi check --staged` and blocks a commit on errors. lipi reports and
preserves an existing pre-commit hook that lacks its marker. Run
`lipi init` after changing the key. The key determines how agent
instructions are rendered, so V3 reports a mismatch until you apply the
new setting. `lipi check` exit codes are always 0 for a clean check, 1
for errors, and 2 for an invalid invocation. The lock file records
the value used to render the instructions.

`lipi init` preserves an existing `lipi.json`. An explicit argument that
conflicts with a setting exits with 2 before writing and points to the
key to edit. Only `.agents/lipi/lipi.lock` holds the setup version.

`release_notes` identifies the documentation page that grows with each
release. D3 skips its size. Link, anchor, and reachability checks still
apply.

## Exclude directories <a id="skip-dirs"></a>

An entry in `skip_dirs` without a slash, such as `fixtures`, excludes
directories of that name at any depth. An entry with a slash, such as
`tests/fixtures`, excludes only that root-relative directory and its
contents. `src/fixtures` and `tests/fixtures-copy` stay included.
Documentation, code, targets, slices, maps, audits, and moves all follow
this rule. Each connected repository uses its own root.

Use `/` as the separator. Repeated separators, `.` components, and
internal `..` components are normalized. `./tests//fixtures/` is
equivalent to `tests/fixtures`. A slash before normalization triggers
path matching, so `fixtures/` and `./fixtures` exclude only the
root-level directory. Absolute paths, paths above the root, and a path
to the root itself raise C1. Matching is literal, with no glob expansion.

## Map and slice layers <a id="layers"></a>

`layers` matches patterns against project-relative paths with `/`
separators. `*` matches any number of characters, `?` matches one, and
`[abc]` matches any of the characters listed. Patterns and layer names
must be nonempty strings. The first match determines the layer. Layers
appear in the order their names first occur in the settings, followed by
the remaining layers in alphabetical order.

```json
{"layers": {"tests/*": "tests", "src/api/*": "api", "src/domain/*": "domain"},
 "tests": ["test_*", "*.spec.*"], "slice_budget": 60}
```

`tests` matches patterns against basenames. An empty array disables
filename matching. Files in the `tests` layer still count as tests.
These settings apply to the map and slice. The set of checks run by
`check` and `audit` is independent of them.

## Repository connections <a id="repos"></a>

```json
{"repos": {
  "core": {"path": "../core", "read": ["docs", "decisions"]},
  "client": {"path": "../client", "read": ["code", "tests"]}
}}
```

Connection names are nonempty and contain lowercase ASCII letters,
digits, and hyphens. Each connection requires exactly two keys.

- `path` is a nonempty path relative to the project root. It may contain
  `..`. Absolute paths and NUL characters are invalid.
- `read` is a nonempty array with unique entries drawn from `docs`,
  `decisions`, `code`, and `tests`. These values authorize read access
  to those scopes.

Wrong types, unknown keys, and unknown scopes raise C1. Paths are
compared after resolving symlinks. Two names for the same root and a
connection to the current project both raise C1. With connections
enabled, a layer name containing `::` also raises C1. A missing directory
is a valid setting for an unavailable source. Omitting `repos` or setting
it to `{}` leaves local behavior as usual.

Reads stay inside the declared source root, including through symlinks.
A connected root nested in the current project is excluded from local
scans and target resolution. The connection reads it instead. Git
filtering runs from each source root before symlinks are resolved.
Git-ignored files are skipped and cannot serve as external targets.
Directories and exclusions come from the neighbor's `lipi.json`.
Its `skip_dirs` paths are relative to its own root. The neighbor's
`history/`, `<workflow>/history/`, and `<decisions>/history/` archives are
skipped even with `docs: "."`. Invalid settings or settings that escape
the neighbor's root make it unavailable. If the neighbor has no
configuration, only explicit `path.md#anchor` targets are available.
A different major version in its lock file makes it unavailable. A
missing lock is allowed. The neighbor's baseline is skipped.

The neighbor's `repos` is read only to identify references back to the
current project's physical root. The two sides may use different names.
The command opens only direct connections. It makes no writes, clones,
or network requests and skips the neighbor's `checks` commands.

Each source record contains HEAD and whether there are uncommitted
changes. In a nested project, HEAD and the dirty flag refer to the
whole repository. A change to a parent's `.gitignore` can affect the
scan. Unknown values are `null`. A source without Git and an unavailable
directory are distinct states. Reproducibility requires available
history and a clean working tree in every source, including the local
project. HEAD is unknown before the first commit.

Write external `@trace` and `covers` targets as
`core::docs/api.md#request` or `core::ADR-018`. An invalid or prohibited
target in an available source raises T1 or D6. An unavailable source
raises T4. A decision path with an anchor requires `decisions` access,
too. External plans, issues, discussions, audits, and agent instructions
are unsupported. Without the neighbor's configuration, target its
explicit `path.md#anchor` addresses only. T2 and A4 apply within a single
repository. A [slice](slice.md#repos) of an external target shows local
code, and a slice of a local target shows consumers in connected
repositories. The [map](map.md#repos) adds their layers and tests.
Unavailable sources still appear in coverage with `T4: off`. In the
`check --structure` graph, external IDs and paths have a `name::` prefix.
The graph stops at external pages.

## Language editions <a id="languages"></a>

Use `languages` to enable multiple documentation editions.

```json
{"docs": "docs/en",
 "languages": {"default": "en",
               "editions": {"en": "docs/en", "ru": "docs/ru"},
               "required": ["en", "ru"]}}
```

Paired pages have the same relative path within their editions, such as
`docs/en/guide.md` and `docs/ru/guide.md`. Each edition has its own
`README.md`. Edition directories cannot be nested inside one another.
Set `docs` to `editions[default]` to use the default edition. A mismatch
raises C1. Write `@trace` and `covers` paths from the project root and
include the directory of the intended edition. With no `languages` key,
documentation uses a single directory.

## Interface language <a id="interface-language"></a>

`lipi lang` displays your current language. `lipi lang ru` saves Russian in
`~/.config/lipi/config.json` for all your projects. The default is English.
An unknown language prints the available choices.

The setting applies to terminal messages and help. Set it before the first
`lipi init` to localize any project starter files that setup creates, including
`AGENTS.md` and starter pages under `docs/` and `workflow/`. Later runs preserve
existing starter files.

The managed rules in `.agents/lipi/` and the GitHub Actions workflow use
English. `lipi guide` prints the English setup guide. Workflow syntax and
lipi's JSON fields and messages also use English. Project text in JSON keeps
its original language. The [`languages`](#languages) key controls documentation
editions.

Each `src/lipi/locale/<language>/` directory supplies `messages.json`,
`terms.json`, and starter templates under `templates/seed/`. Missing
translations fall back to English. The translation inventory lists missing
entries and changed English sources.
