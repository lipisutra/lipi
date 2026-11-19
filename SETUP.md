# Set up lipi in a project

Use this guide when a person or AI agent is asked to set up lipi.
`lipi guide` prints the same instructions. See the
[English documentation](docs/en/README.md) or the
[Russian documentation](docs/ru/README.md) for the rules, settings,
and check codes. `lipi version --path` shows the installed checker's
path. English templates for managed files live next to it in
`locale/en/templates/lipi/`, and localized starter files in
`locale/<language>/templates/seed/`.
The installed package also includes both documentation editions
and images under `share/lipi/`, preserving their repository paths.

## Install <a id="install"></a>

Install the `lipi` command once per machine with [pipx](https://pipx.pypa.io/).

```bash
pipx install git+https://github.com/lipisutra/lipi   # Install
pipx upgrade lipi                                  # Upgrade
```

lipi requires Python 3.9 or later. To develop lipi, run
`pipx install --editable .` from the cloned repository. The installed
`lipi` command runs project checks (ADR-010). The project keeps settings,
rules, and state. Install lipi on machines that run checks. Agents
can read the rules from the project files without it.

`.agents/lipi/lipi.lock` records the full version of the deployed rules;
V1 compares its major version with the installed program.
To work with a specific major version, install a separate copy of
the command. For example, for 1.x:

```bash
pipx install --suffix @1 git+https://github.com/lipisutra/lipi@v1
lipi@1 check
```

The V1 message identifies the required major version from the lock file.

## Initialize a project <a id="init"></a>

`lipi init` applies the installed lipi version. The presence of
`.agents/lipi/lipi.lock` distinguishes a repeat application from a
first setup. With no lock, setup is new even if `lipi.json` exists.

1. For a new project, choose a package or an application with
   separate help, and pick documentation and workflow directories.
   Defaults are package, `docs/`, `workflow/`, and enforcement off.
2. English is the default. For Russian terminal output and project starter
   files, run `lipi lang ru` before the first `lipi init`. The managed rules
   and GitHub Actions workflow use English. Run `lipi init` from the project
   root.

   Choose one form and run it once. Preview it first with `--dry-run`,
   for example `lipi init --type app --dry-run`, then `lipi init --type app`.
   After setup, `lipi.json` keeps the choice: an argument that conflicts
   with it is an error, so change settings in `lipi.json` instead.

   ```bash
   lipi init                              # Package, default directories
   lipi init --type app                    # Application with separate system documentation
   lipi init --workflow work               # Custom workflow directory
   lipi init --enforce                     # Enforce rules in a new project
   ```

   Use `--docs` and `--workflow` for custom directories. If
   `lipi.json` exists, any explicit arguments must match it. A
   mismatch stops the command before writes and identifies the key
   to edit. Init preserves the existing file.
3. First setup preserves existing files. Without `lipi.json`, it
   creates settings and missing scaffolds. With `lipi.json`, it
   keeps settings and scaffolds and creates missing lipi files.
   It keeps an existing baseline or creates one from current errors.
4. A repeat run replaces or restores lipi-managed files and reports
   overwritten edits by comparison with the lock. Check for
   `Will replace your edits in` messages in the dry run. Project
   scaffolds and the baseline are preserved and missing ones stay absent.
   Corrupt settings or a corrupt lock, or a lock without `lipi.json`,
   stops the run before any writes. See the
   [init state table](docs/en/commands.md#update).
5. Keep an existing `AGENTS.md` and add its link to
   `.agents/lipi/README.md` if missing. A scaffolded file has it.
6. `enforce` in `lipi.json` controls strictness. With `true`, init
   installs lipi's `lipi check --staged` pre-commit hook; this requires a
   `.git` directory directly in the project root. With `false`, it removes
   an existing lipi hook. A hook not installed by lipi is preserved.
   Apply the new setting with `lipi init`. Until then, V3 reports
   a mismatch.
7. Run `lipi check`. A first setup can record existing errors in
   the baseline. `lipi check --no-baseline` shows them all.
   Reapplying rules leaves the baseline unchanged. Fill in new
   documentation with verified facts and preserve existing documentation.
8. [Report the result](#report). Commit only if the user asks.

If the workflow directory contains another format, such as plans
under `current/` and `completed/`, a first setup without settings
writes `"workflow": null` and suggests
[importing the documents](#existing-workflow) with `lipi migrate`.

Project rules are preserved. Report friction with lipi-managed
`.agents/lipi/` files as an issue.

## Apply rules to an initialized project <a id="update"></a>

Run `pipx upgrade lipi` first. See the upgrade instructions in
[CHANGELOG](CHANGELOG.md) to determine whether to apply the rules.
`lipi init` applies bundled files locally and reports the source
version. `--dry-run` previews the plan without creating files,
directories, hooks, or a baseline. A repeat run writes only changes.

If workflow documents already follow the format and sit directly
under their type directories, `lipi init` can
[organize them by year](docs/en/workflow.md#upgrade). Preview with
`lipi init --dry-run`.

### Reduce existing debt <a id="tighten"></a>

Keep the checks enabled and fix existing errors, then remove them
from the baseline with `lipi baseline --prune`. Only an explicit
baseline write can add new errors.

| Area | Setting or command | Project work |
| --- | --- | --- |
| Documentation debt | `lipi baseline --prune` after fixes | Fix documentation errors. |
| Workflow documents | `"workflow": "workflow"` | Run `lipi migrate workflow --apply`, then `lipi baseline`. |

### Import an existing project's workflow documents <a id="existing-workflow"></a>

Use `lipi migrate` for legacy plans, issues, and audits.

```bash
lipi migrate workflow            # Preview a migration from workflow
lipi migrate workflow --apply    # Apply it. Substitute your workflow path if different.
```

The command requires Git and a clean working tree. Files move through
`git mv` so `git status` shows the moves and they can be undone.
The default directory comes from `workflow` in `lipi.json`. When you
pass a different path, the command records it in settings so the
checker can read it. After init sets `"workflow": null` for a legacy
project, pass the directory explicitly for both preview and apply.
The preview lists the destinations, dates, and sources and ends with
the command to apply the plan. Applying records the directory in settings.

With `--apply`, the command:

- Moves PLN, ISS, DSC, and AUD into type and creation-year directories
  such as `plan/YYYY/` and `issue/YYYY/`. ADR stays flat. It preserves
  IDs and assigns the next available ID of its type to unnumbered
  documents and branches named like `011-1`.
- Sets status from the directory, such as `completed` to `completed`
  and `backlog` to `deferred`, or from the header. It uses header
  dates when present and otherwise the first and last Git commits
  for the file. If the creation date and history are absent, it
  uses the migration date. It preserves a final document's valid `Closed`
  or derives it from closure history. It can use `Updated` for legacy
  material without a standard header or files with no Git history.
- Accepts legacy Russian headers and writes English fields, statuses,
  kinds, and required headings. It fills a missing `Result` on a
  completed or canceled plan or a closed issue with text such as
  `Not recorded (migrated 2026-11-19)`. A missing or unrecognized issue
  `Kind` defaults to `question`.
- Updates relative links in all project Markdown files.
- Archives the previous closure log, master plan, and reports under
  `history/`. It creates an empty master plan and scaffolds
  `workflow/README.md` if needed.
- Records old path, new path, and ID in `history/MIGRATION.md` and
  regenerates the index.

Use `migrate.json` in the workflow directory to override a file's
type, status, and number. See the [migration schema](docs/en/commands.md#migrate).
After migrating, run `lipi baseline` to record existing content
findings such as empty sections, oversized pages, and forbidden
links from documentation to workflow documents.

## Report to the user <a id="report"></a>

- List what was created. The project commits `lipi.json`, managed
  `.agents/lipi/` files (`README.md`, `documentation.md`,
  `workflow.md`, and `lipi.lock`), a newly created baseline at
  `.agents/lipi/baseline.json`, scaffolded `AGENTS.md`, and
  documentation and workflow directories. The installed `lipi`
  command runs checks. The hook for `"enforce": true` is local
  under `.git/hooks/`.
- State the defaults used, including project type and workflow
  directory.
- In an existing project, report the number of errors recorded
  in the baseline, which findings remain visible, and
  [how to reduce debt](#tighten). If legacy workflow documents
  are excluded from checks, mention `lipi migrate`.
- State what the user still needs to do.

## Report friction <a id="friction"></a>

If setup is unclear or a check behaves unexpectedly, run `lipi doctor`.
It reads Python and lipi versions, the lock, the pre-commit hook,
the index, and the baseline, and suggests a next command when needed.

When a rule hinders the work, the checker is wrong, or instructions
leave an important gap, file an issue in the project and tell the
user.

```bash
lipi new iss "What got in the way and when" friction lipi
```

Describe what hindered the work or required guessing, and fill in
the generated sections. With no workflow directory configured, the
issue goes to `.agents/lipi-feedback/`. The checker treats it as an
issue, and `lipi collect` imports it alongside issues in
`workflow/issue/YYYY/`.

## Connect neighboring repositories <a id="repos"></a>

Configure [`repos` connections](docs/en/settings.md#repos) for shared
documentation or consumers in a neighboring directory. `docs` and
`decisions` permit external targets. `code` and `tests` permit reverse
lookup of the neighbor's trace markers. For example,
`lipi slice core::docs/api.md#request` shows local code for an
external section. A slice of a local section shows consumers found
in neighbors. `lipi map` adds columns for their layers and tests.
Each side can use a different connection name because matching
uses physical roots. Commands read explicit connections only and
report coverage, HEAD, dirty trees, and unavailable sources. See
[connected slice behavior](docs/en/slice.md#repos) and
[connected map behavior](docs/en/map.md#repos).
