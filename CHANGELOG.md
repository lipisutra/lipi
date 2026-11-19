# lipi releases

## 1.1.0 — 2026-11-20

- A connection can extend its `docs` scope with `page_dirs`. Trace markers,
  slices, and maps use the same set of pages.
- When a local phrase has no match, `lipi slice` suggests commands to search
  connected repositories. JSON clients receive the commands in `suggestions`.
  A title match in a neighbor includes an openable path in text output.

### Проекту при обновлении

1. Обновите программу: `pipx upgrade lipi`.
2. Правила и шаблоны не изменились — `lipi init` не нужен.

Update Lipi before adding `page_dirs` to `lipi.json`. Version 1.0.1 reports C1
for this key.

## 1.0.1 — 2026-11-20

- `lipi slice` counts marked test locations and explains how to read them.
  With connected repositories it reports local staleness coverage and how many
  locations have cross-repository links outside that check. The JSON schema remains at version 1.
- The plans shown by `lipi init` and `lipi mv` mention an archive only when it exists.
- `lipi new pln` omits a leading `Plan:` or `План:` from the generated filename.

### Проекту при обновлении

1. Обновите программу: `pipx upgrade lipi`.
2. Правила и шаблоны не изменились — `lipi init` не нужен.

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
