# Lipi source files

To develop Lipi, run `pipx install --editable .` from the clone. To run a
command directly from source, use the entry point, for example
`python3 src/lipi/cli.py check`.

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
- [CHANGELOG.md](../../CHANGELOG.md) records release changes.

## Checker modules <a id="checker"></a>

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
