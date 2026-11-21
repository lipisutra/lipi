# lipi

<p align="center"><img src="docs/assets/logo.png" alt="lipi" width="380"></p>

<h3 align="center">Where is this implemented, who uses it, and which tests should I read?</h3>

<p align="center">
  <a href="https://github.com/lipisutra/lipi/releases/latest"><img src="https://img.shields.io/github/v/release/lipisutra/lipi" alt="Latest release"></a>
  <a href="#install"><img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python 3.9+"></a>
  <a href="docs/ru/README.md"><img src="https://img.shields.io/badge/docs-%D0%A0%D1%83%D1%81%D1%81%D0%BA%D0%B8%D0%B9-blue" alt="Документация на русском"></a>
</p>

Lipisutra (Lipi) connects Markdown documentation and decisions to the code
and tests that reference them. Developers and coding agents can follow a
feature across the repositories they connect.

For example, before adding support for reading a saved revision, run
`lipi slice 'docs/records.md#read-revision'`. It lists the implementation,
consumers, and tests marked for that contract.

[Try Lipi on one task in an existing project](docs/en/first-task.md).

## What you can do with Lipi

- **Find existing behavior.** Run `lipi map` to see which concepts have
  markers in each layer. Open a concept with `lipi slice` to find the
  linked decisions, code, and test locations. If you only have a question, try
  `lipi slice --search 'Can I read a saved revision by ID?'`.
- **Review a change.** Run `lipi slice --diff HEAD` for related locations
  in your project and its connected repositories. When the diff touches
  several targets, each location shows the targets it shares with the change.
- **Keep documentation current.** `lipi check` finds broken links and
  trace targets. `lipi audit` uses local Git history to flag sections
  worth rereading when the code changes.
- **Keep decisions close to the work.** Store decisions and, if useful,
  plans, issues, and discussions as Markdown in Git. Link code to a
  decision by its stable ID and use `lipi index` to refresh the workflow index.

## Install <a id="install"></a>

Install once per machine with [pipx](https://pipx.pypa.io/) and Python 3.9 or later.

```bash
pipx install git+https://github.com/lipisutra/lipi@v1
lipi version
```

To update within 1.x, run `pipx upgrade lipi`.

To remove Lipi from this machine, run

```bash
pipx uninstall lipi
```

## Initialize a project <a id="init"></a>

From the project root, preview setup and then apply it.

```bash
lipi init --dry-run
lipi init
lipi check
```

For an application with separate user help, add `--type app` to both
`init` commands. For Russian terminal output and starter files, run
`lipi lang ru` before the first setup. Managed agent rules are in English.
Commit the project configuration, rules, and state so the team shares them.

## Existing projects

Use `--docs` to point setup at your existing documentation. The first
`init` preserves project files and can record existing errors in a baseline.
If your project already has an `AGENTS.md`, add a link there to
`.agents/lipi/README.md`. Teams can start with one contract and add
markers as they work. [Existing project setup](SETUP.md#init) ·
[Connecting two repositories](docs/en/first-task.md#repos).

## Documentation

- [English documentation](docs/en/README.md) · [Документация на русском](docs/ru/README.md)
- [Setup guide](SETUP.md), also available with `lipi guide`
- <a id="codes"></a>[Check codes](docs/en/codes.md) and [project settings](docs/en/settings.md)
- [Releases and upgrade instructions](CHANGELOG.md)
- <a id="source-files"></a>[Source files and checker modules](docs/en/source-files.md) · [Contributor instructions](.agents/README.md)
