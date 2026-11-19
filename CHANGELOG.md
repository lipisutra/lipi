# lipi releases

## 1.0.1 — Unreleased

- `lipi slice` counts marked test locations and explains how to read them.
  With connected repositories it reports local staleness coverage and how many
  locations have cross-repository links outside that check.

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
