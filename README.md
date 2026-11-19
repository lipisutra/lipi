# lipi

<p align="center"><img src="docs/assets/logo.png" alt="lipi" width="380"></p>

<h3 align="center">Lipisutra — structured documentation and knowledge management.</h3>

<p align="center">Write. Link. Organize.</p>

lipi provides rules, a scaffold, and a checker for project documentation.
It is designed primarily for new projects.

Install lipi once per machine. Run `lipi init` to create a project's
configuration, rules, and state. The installed `lipi` command runs
the checks (ADR-010). Commit the generated files with the project.
Agents can read the rules even without lipi installed. To change lipi
itself, see the [agent instructions](https://github.com/lipisutra/lipi/blob/v1.0.0/.agents/README.md).

## Documentation

The [English edition](docs/en/README.md) and [Russian edition](docs/ru/README.md)
cover commands, settings, rules, check codes, maps, and slices.
See [SETUP.md](SETUP.md) for project setup and [CHANGELOG.md](CHANGELOG.md)
for release history and upgrade steps.

## Install <a id="install"></a>

Install once per machine with [pipx](https://pipx.pypa.io/).

```bash
pipx install git+https://github.com/lipisutra/lipi
```

lipi requires Python 3.9 or later. pipx uses it to create the environment.
To upgrade to the latest version, run:

```bash
pipx upgrade lipi
```

To develop lipi, run this from the cloned repository.

```bash
pipx install --editable .
```

Use `lipi version` and `lipi help` to verify the installation.

```bash
lipi version
lipi help
```

To remove lipi:

```bash
pipx uninstall lipi
```

The installed `lipi` command is available from any directory. To run
commands from a clone without installing, use `python3 src/lipi/init.py`,
`python3 src/lipi/check.py`, and the other modules under `src/lipi/`.

## Initialize a project <a id="init"></a>

You can ask an AI agent to set up lipi in your project. It can follow
[SETUP.md](SETUP.md) for the steps and settings. `lipi guide` prints the
same instructions.

Before the first `lipi init`, run `lipi lang ru` if you want Russian terminal
output and project starter files. The managed rules and GitHub Actions
workflow use English. See the [interface language settings](docs/en/settings.md#interface-language).

Run `lipi init` once from the project directory, choosing one form.
Preview with `--dry-run` first.

```bash
lipi init              # Package
lipi init --type app   # Application
```

`lipi init` applies the version installed on the machine. With no lock
file, it runs first-time setup. With `.agents/lipi/lipi.lock`, it reapplies
the rules. It creates settings and scaffolds only when `lipi.json` is
absent, and preserves existing project files. A repeat run replaces or
restores lipi-managed files and reports overwritten changes. Deleted
scaffolds and baselines stay deleted. Preview the plan with
`lipi init --dry-run`. Init can also organize
[existing workflow documents](docs/en/workflow.md#upgrade) by year.
Use `--docs` and `--workflow` for custom directories. An argument that
conflicts with an existing `lipi.json` produces an error. See the
[init command reference](docs/en/commands.md#update).

The project controls enforcement. By default, `lipi check` reports
findings and setup installs no pre-commit hook. Set `"enforce": true`
in `lipi.json` and run `lipi init` to enable the `lipi check --staged`
pre-commit hook and strict agent instructions (ADR-011). lipi preserves
hooks owned by the project. After changing the setting, run
`lipi init`. Until then, V3 reports the mismatch.

## Existing projects

Use `lipi init` when the project already has documentation, workflow
documents, or an `AGENTS.md`. First-time setup preserves existing files.
Add the link to `.agents/lipi/README.md` to an existing `AGENTS.md`.
A new baseline at `.agents/lipi/baseline.json` records existing errors.
Checks still run and fail on new errors. Use `lipi migrate` to import
existing documents. See [SETUP.md](SETUP.md#init) for setup and project debt.

## Source files

- [src/lipi/cli.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/cli.py) provides the `lipi` entry point.
- [src/lipi/init.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/init.py) initializes and updates projects.
- [src/lipi/check.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/check.py) starts the checker on Python 3.9+ with no external dependencies.
- [src/lipi/checker/](https://github.com/lipisutra/lipi/tree/v1.0.0/src/lipi/checker/) contains the checker modules listed below.
- [src/lipi/sources.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/sources.py) models connected sources, read boundaries, and Git state.
- [src/lipi/collect.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/collect.py) gathers lipi feedback from projects.
- [src/lipi/migrate.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/migrate.py) converts an existing project's workflow documents to the lipi format.
- [src/lipi/doctor.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/doctor.py) diagnoses project versions, pre-commit, indexes, and the baseline.
- [src/lipi/slice.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/slice.py) runs slices. `slice_index.py` gathers links, `slice_query.py` selects results, `slice_diff.py` reads Git changes, and `slice_output.py` applies limits and renders output.
- [src/lipi/map.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/map.py) builds a map from the shared slice index without history or project checks.
- [src/lipi/repo_index.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/repo_index.py) indexes direct connections. `repo_slice.py` gathers their slice data and `repo_output.py` reports source state and coverage.
- [src/lipi/locale/en/templates/](https://github.com/lipisutra/lipi/tree/v1.0.0/src/lipi/locale/en/templates/) holds setup templates for `.agents/lipi/` and project scaffolds in `seed/`.
- [pyproject.toml](https://github.com/lipisutra/lipi/blob/v1.0.0/pyproject.toml) defines the package and installation.
- [CHANGELOG.md](CHANGELOG.md) records release changes.

| Module under `src/lipi/checker/` | Responsibility |
| --- | --- |
| `conventions.py`, `config.py` | Shared conventions, settings, and state schemas |
| `model.py` | Markdown pages, the project model, and file selection |
| `report.py` | Findings, severity levels, and output formats |
| `docs.py`, `workflow.py` | Documentation, language editions, and workflow documents |
| `trace.py`, `audit.py` | Trace markers, discrepancies, and Git history audits |
| `targets.py` | Shared resolution of `@trace` and `covers` sections and work item IDs |
| `history.py` | Git history of regions, including code moves |
| `state.py` | Version compatibility, lipi files, and the baseline |
| `structure.py` | The link graph and staleness chains |
| `commands.py`, `runner.py` | Command operations and check sequencing |

[src/lipi/__init__.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/__init__.py) defines the shared version
for the rules, scaffold, and checker.

## Check codes <a id="codes"></a>

See the [check code reference](docs/en/codes.md) for what each check
covers. Codes are permanent identifiers with a stable meaning across
versions. CI, the baseline, and people reading output rely on them.

`CHANGELOG.md` is exempt from the page size limit because `release_notes`
identifies it in `lipi.json`. See [settings](docs/en/settings.md).
