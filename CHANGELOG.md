# lipi releases

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
