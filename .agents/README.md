# Instructions for contributors

[Русский](ru/README.md)

Use these instructions when changing lipi itself. To set up lipi in another project, start with the [README](../README.md).

## Repository layout <a id="map"></a>

| Path | Purpose |
| --- | --- |
| `docs/{en,ru}/rules.md` | Rules and their rationale for people and agents |
| `commands.md`, `settings.md`, `codes.md` in each edition | Commands, configuration keys, and check codes |
| `SETUP.md` | Setup instructions printed by `lipi guide` |
| `src/lipi/locale/en/templates/lipi/` | Managed rules written to `.agents/lipi/` and the template for `.github/workflows/lipi.yml`, all in English |
| `src/lipi/locale/<language>/templates/seed/` | Initial project files such as `AGENTS.md` and documentation and workflow pages |
| `src/lipi/cli.py` | Entry point for the installed command |
| `src/lipi/check.py`, `src/lipi/checker/` | Checker entry point and implementation. See the [checker module table](../docs/en/source-files.md#checker). |
| `src/lipi/__init__.py` | Version shared by the checker, rules, and scaffolds |
| `src/lipi/init.py` | Initial setup and updates to managed files |
| `src/lipi/collect.py`, `src/lipi/migrate.py` | Collect feedback and convert existing workflow documents |
| `src/lipi/move.py`, `move_links.py`, `move_neighbors.py`, `move_reviews.py` | Plan moves, update links and review marks, report affected connections, and roll back changes |
| `src/lipi/review.py`, `checker/reviews.py` | Review A4 pairs, compute fingerprints, validate and prune the registry |
| `src/lipi/doctor.py` | Diagnose project setup |
| `src/lipi/slice.py`, `slice_index.py`, `slice_query.py`, `slice_diff.py`, `slice_output.py` | Resolve a target or Git diff, collect related items, and render a bounded slice |
| `src/lipi/map.py` | Map direct trace markers by layer and test using the shared index |
| `src/lipi/repo_index.py`, `repo_slice.py`, `repo_output.py`, `sources.py` | Direct repository connections, settings, read boundaries, source status and coverage |
| `pyproject.toml`, `tests/` | Packaging and unittest modules grouped by check or feature |
| `workflow/`, `CHANGELOG.md` | Work items and decisions, release changes and upgrade instructions |

lipi follows its own project rules. From the clone, install it with `pipx install --editable .` and run `lipi check`. See the [installation instructions](../README.md#install).

## Scope <a id="boundaries"></a>

- Plans, issues, discussions, and decisions in this repository cover lipi's rules, templates, checker, scripts, tests, and documentation.
- Plan and track changes to another project there, under its own rules. A lipi work item's completion criteria cover work in this repository.
- Keep other projects' names and identifying details out of documents, tests, and commit messages. Anonymize external feedback and use synthetic, general-purpose test fixtures.

## Making changes <a id="change"></a>

Change a rule, its template, and its check in the same commit.

1. Start with a request or an issue in the [workflow index](https://github.com/lipisutra/lipi/blob/master/workflow/INDEX.md). To collect feedback, run `python3 src/lipi/collect.py <project>` from this checkout.
2. Update `docs/{en,ru}/rules.md` for the rule and its rationale, the relevant template under `src/lipi/locale/` for the agent instructions, and the corresponding checker module under `src/lipi/checker/`.
3. Cover a new check with a case in `tests/`.
4. For a change in behavior, update `src/lipi/__init__.py` and `CHANGELOG.md` according to the [release procedure](#release).
5. Choose [checks](#checks) that exercise what changed.
6. Include the work item ID in the commit message. A5 uses it to check whether the status is up to date.

Add rules that the checker can enforce or that an agent can follow from a single sentence. Keep project-specific language and stack conventions in the relevant project. Use the Python standard library for the checker.

To add an interface language, create a sibling of `src/lipi/locale/en/`. Each translated message or term has `text` and `source_sha256`. For a term, `text` contains `term` and `definition`. In `template-hashes.json`, use the seed file's path relative to `templates/` as its key. The managed rules and CI template always come from English. Use `lipi.i18n.fingerprint` on the English value or UTF-8 template text and update the fingerprint after reviewing the translation. Check the translation inventory with `python3 -m unittest tests.test_interface_language.LanguageResources.test_translation_inventory`.

### Design questions for manual input <a id="manual-input"></a>

Before adding a field, relationship, or attribute that authors enter by hand, answer four questions.

1. Does the author already know the answer when making the change?
2. Can Lipi derive it from paths, layers, Git history, or existing links?
3. How would this information change a reader's decision or the result of a check?
4. How will readers see what is still unknown when only some locations have this information?

## Documentation <a id="documentation"></a>

The root documentation pages and the [reference](../docs/en/README.md) follow the same [documentation rules](https://github.com/lipisutra/lipi/blob/master/src/lipi/locale/en/templates/lipi/common/documentation.md) as other projects.

## Workflow documents <a id="workflow"></a>

Follow the [workflow instructions](https://github.com/lipisutra/lipi/blob/master/workflow/README.md). Report friction encountered here with `lipi new iss "What got in the way" friction`.

## Checks <a id="checks"></a>

See [Verification and reflection in the repository’s AGENTS.md](https://github.com/lipisutra/lipi/blob/master/AGENTS.md#verification-and-reflection).

After a clean pipx install, run [tests/check_package.py](https://github.com/lipisutra/lipi/blob/master/tests/check_package.py) with the installed environment's Python. Pass `--source` pointing to a snapshot of the same revision. Run outside the checkout and snapshot with `PYTHONPATH` unset. The test checks installed documentation and `lipi guide` against the snapshot and imports modules from the installation.

Commit or publish when the user authorizes it.

## Release procedure <a id="release"></a>

Bump the version on the first task in a release that changes behavior. Include the entry in `CHANGELOG.md` in the same commit. The `vX.Y.Z` tag identifies the release commit containing that entry. See [ADR-001](https://github.com/lipisutra/lipi/blob/master/workflow/adr/adr-001-net-naslediya-sovmestimost-s-prezhnimi-versiyami.md).

1. After the first release, include the required upgrade section in each entry. The release test expects the heading `Upgrading your project` and two numbered steps, each on its own line. The first upgrades the program and the second says whether to run `lipi init`. Follow this format:

   ```text
   1. Upgrade Lipi with `pipx upgrade lipi`.
   2. The rules and templates are unchanged. You can skip `lipi init`.
   ```

   When rules or templates changed, use the exact line below.

   ```text
   2. The rules and templates have changed. Run `lipi init`.
   ```

   To install a specific release, use `pipx install --force git+https://github.com/lipisutra/lipi@vX.Y.Z` with that entry's tag. Put further project-specific steps after the first two.
2. Run `tests/test_release.py`. The version in `src/lipi/__init__.py`, the top entry in `CHANGELOG.md`, and `.agents/lipi/lipi.lock` must agree.
3. Create the annotated release tag and push it:

   ```bash
   git tag -a vX.Y.Z -m "lipi X.Y.Z"
   git push origin vX.Y.Z
   ```

4. Pushing `vX.Y.Z` starts the full GitHub Actions matrix automatically. Wait for
   the tag's required checks. The full suite must pass on Ubuntu and macOS. On
   Windows, the CRLF and repository path checks must pass on Python 3.9 and 3.x.
   Until [ISS-033](https://github.com/lipisutra/lipi/blob/master/workflow/issue/2026/iss-033-vosstanovit-obyazatelnyy-polnyy-progon-na-windows.md)
   closes, the job summary reports the full Windows results for reference.
   The two-second CLI budget runs on Ubuntu 24.04 with Python 3.9.

   Branch pushes, pull requests, and updates to `v1` run quick checks covering the
   release metadata, package installation, project audit, and Windows portability.
   For a full run on request, select **Actions → test → Run workflow** or run
   `gh workflow run test.yml --ref <branch-or-tag>`.
5. Once the required checks pass, move the major tag to the same commit, push it,
   and publish the GitHub release.

Move the major tag (for example, `v1`) to each release in its series. Projects use that tag for CI installations under ADR-010. Within a major version a new check starts as a warning. ADR-022 allows T5 to start as an error in 1.x because it validates an explicit `role=…` attribute. Raising a warning to an error requires a new major version. The release test compares `CODE_LEVELS` with the `v<major>.0.0` tag. Until that tag exists it skips only the level comparison. It still checks the package version, changelog, and lock. If an existing tag cannot be read, the test fails. List new error levels in the changelog when changing the major version.

An incompatible change to project syntax (trace markers, `covers`, workflow headers and filenames, or anchors) requires an automatic migration. The new `lipi init` must rewrite the old form or print an exact plan. Test that path on a project using the previous format. A changelog instruction alone cannot migrate thousands of markers.

Under ADR-009, `lipi init` replaces managed files in full. The package contains the current templates.
