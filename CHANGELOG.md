# lipi releases

## 1.4.3 — 2026-11-27

- Clean Git checkouts with LF or CRLF pass the managed-file and workflow
  index checks. Existing Windows lock fingerprints remain valid.
- Connected repository paths must be relative to the project on every OS.
  Paths with a root, drive prefix, or UNC share raise C1. Siblings such
  as `../neighbor` are supported.

### Upgrading your project for 1.4.3

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

## 1.4.2 — 2026-11-27

- A missing link to Lipi rules in `AGENTS.md` (V2) now fails `lipi check`
  at error level even if an older baseline contains V2. New baselines omit
  V2. Adding the link resolves the finding immediately.

### Upgrading your project for 1.4.2

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

## 1.4.1 — 2026-11-26

- Document text search gives several matching words in a paragraph a better
  chance of outranking an isolated question word. A distinctive term such as
  `API` can still outrank several common words.

### Upgrading your project for 1.4.1

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

## 1.4.0 — 2026-11-22

- `lipi slice --search 'question'` searches document headings and paragraphs.
  Each candidate includes a slice target, an excerpt, and a file and line to
  open. Use `name::question` to search one connected repository.
- When a text query misses, `lipi slice` suggests a search command for the
  same words. The agent instructions and first-task guide explain how to
  follow a match or try a connected repository.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.3.3 — 2026-11-21

- Agent instructions explain how to tell which part of a behavior a linked
  test confirms and how to report what remains unverified.
- The first-task guide explains how to choose a link worth marking and when
  a role helps a reviewer decide which code to open.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.3.2 — 2026-11-21

- The workflow rules explain when to ask the user to accept a decision or a
  completed plan, and how to refine or replace an accepted decision.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.3.1 — 2026-11-21

- Without a settings file, `lipi check` and `lipi audit` can check existing
  documentation and leave an unrelated `workflow/` directory untouched.
  `lipi baseline` and `baseline --prune` require a settings file. Run
  `lipi init` to configure the project.
- For an explicit Markdown address in a connected repository, `lipi slice`
  explains which read setting, file path, or anchor to check. JSON includes
  the cause in `reason` (schema 1). A query without an anchor in a neighbor
  without `lipi.json` returns `reason: no-config`.
- Agent instructions explain when to start with a section slice or a concrete
  symptom and when to link an issue to the documented behavior.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.3.0 — 2026-11-21

- `lipi slice --diff` and `--staged` show the old and new wording of changed
  Markdown sections alongside linked code and tests, in text and JSON. They
  distinguish changed markers from references still pointing at a deleted
  anchor.
- Code trace markers can declare `role=consumes`, `role=produces`, or both
  for a Markdown anchor. `lipi check` reports an invalid role or an invalid
  use of the attribute as T5. Its default level is `error`.
- `lipi slice` accepts `--role consumes` and `--role produces` for a target,
  a Git diff, or staged changes. Results include locations with missing or
  unrecognized roles. A removed link shows its role before the change.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.2.1 — 2026-11-20

- First-time setup calculates the baseline directly in the project. It no longer
  copies the project into a temporary directory. A dry run previews baseline
  creation without calculating it.
- The setup guide explains when to exclude data directories with `.gitignore`
  or `skip_dirs`.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

## 1.2.0 — 2026-11-20

- `lipi check` now reports which managed files `lipi init` would add, update,
  or stop managing. After upgrading Lipi, projects with older rules can see
  these V4 warnings both locally and in CI.
- `lipi slice --diff` and `lipi slice --staged` label related locations when
  multiple targets are affected. JSON location items include all matching
  targets in `matched_targets` with the existing `via` values preserved.
- The setup guide links to a walkthrough for existing projects. Managed
  agent instructions explain when to read a linked assertion and run its test.
- A symlink loop in a repository connection path now reports C1 on Python 3.13
  and later, as it does on earlier supported versions.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

If V4 reports unapplied changes from earlier releases, preview them with
`lipi init --dry-run`. Upgrade all checkers before configuring V4 in
`codes`: Lipi 1.1.x rejects that key with C1 (exit code 2).

To switch an existing pipx installation from the default branch or an exact tag to 1.x updates, run `pipx install --force git+https://github.com/lipisutra/lipi@v1` once.

## 1.1.1 — 2026-11-20

- Agent instructions explain when to follow a suggested repository search
  and how to trace a shared contract to the same anchor across components.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates have changed. Run `lipi init`.

## 1.1.0 — 2026-11-20

- A connection can extend its `docs` scope with `page_dirs`. Trace markers,
  slices, and maps use the same set of pages.
- When a local phrase has no match, `lipi slice` suggests commands to search
  connected repositories. JSON clients receive the commands in `suggestions`.
  A title match in a neighbor includes an openable path in text output.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

Update Lipi before adding `page_dirs` to `lipi.json`. Version 1.0.1 reports C1
for this key.

## 1.0.1 — 2026-11-20

- `lipi slice` counts marked test locations and explains how to read them.
  With connected repositories it reports local staleness coverage and how many
  locations have cross-repository links outside that check. The JSON schema remains at version 1.
- The plans shown by `lipi init` and `lipi mv` mention an archive only when it exists.
- `lipi new pln` omits a leading `Plan:` or `План:` from the generated filename.

### Upgrading your project

1. Upgrade Lipi with `pipx upgrade lipi`.
2. The rules and templates are unchanged. You can skip `lipi init`.

## 1.0.0 — First release

- Set up rules and starter files for packages and applications with `lipi init`.
- Check documentation, workflow documents, and links to code. A baseline
  records existing errors so teams can adopt lipi and track outstanding work.
- Use a slice to explore a target or Git diff, and a map to find related code
  and tests. Connect neighboring repositories explicitly.
- Move pages and directories while updating links and trace markers. Import
  existing workflow documents and index work items by status and closure date.
- Audit documentation for staleness and record review marks for individual
  links between code and documentation.
