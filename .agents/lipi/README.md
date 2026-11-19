# lipi rules

For anyone changing the project, including AI agents. Project users start
with the [documentation](../../docs/en/README.md).

## Three layers <a id="layers"></a>

| Layer | Where | What it contains | When it must be accurate |
| --- | --- | --- | --- |
| Documentation | `docs/en/` | what the project does and how to use it | always |
| Workflow documents | `workflow/` | plans, issues, discussions, decisions, audits | as of their date |
| Rules | `AGENTS.md`, `.agents/lipi/` | how to change the project | always |

Keep work in progress out of the documentation. Links from documentation
into the workflow directory, including its indexes, are allowed only for
decisions. Workflow documents can link to documentation.
Decisions can live in the directory configured under `decisions` in
`lipi.json`. It defaults to `adr/` inside the workflow directory. See their
rules in [Workflow documents](workflow.md).

## What to read for each type of change <a id="by-subject"></a>

| Change | Rules |
| --- | --- |
| Documentation, README, examples | [Documentation](documentation.md) |
| Plan, issue, discussion, decision, audit | [Workflow documents](workflow.md) |

## Working on a task <a id="task"></a>

- Start with `lipi slice` for a concept, source file, or work item ID. Read
  the relevant files, make the change, verify it, and report the result.
  Try `lipi slice docs/en/api.md#requests`, `lipi slice src/api.py`, or
  `lipi slice ISS-001`. If the slice is empty, look for related files yourself.
- After editing code, review its links with `lipi slice --diff HEAD` or
  `lipi slice --staged`. The slice lists things to check.
- Create a plan, audit, or discussion when the user asks for one. You can
  complete a task without creating a workflow document.
- Update documentation about changed behavior in the same commit.
- Include the work item ID in any commit that advances it so the audit can
  detect stale statuses.
- Record a bug or friction you defer in an [issue](workflow.md#issue).
- Commit and publish only at the user's explicit request.

If you are still scoping the task, `lipi map` shows traces by code layer and
test. Zero means that lipi found no links. When `repos` is configured,
slices and maps show permitted links to connected repositories. Account
for their read scopes, HEAD, dirty trees, and unread sources even if T4 is off.

## Friction with the rules <a id="friction"></a>

The project gets these rules from lipi, and the installed `lipi` command
checks them. If a rule gets in your way, a check is wrong, or a rule is
missing, file an issue addressed to lipi:

```bash
lipi new iss "What got in the way and when" friction lipi
```

Describe what you tried, what got in the way, and how you worked around it.
These issues can be collected in lipi and used to improve it. Leave lipi's
managed files in the project intact so their fingerprints match.

## Checks <a id="checks"></a>

`lipi init` applies rules from the installed package. Use `--dry-run` to
see the plan before it writes anything. Change project settings in
`lipi.json` before running init. Repeat runs replace managed lipi files,
report any local edits they replace, and keep project files and the baseline.
A repeat run can also move workflow documents from an older layout into
year directories and rewrite the paths that refer to them; `--dry-run`
shows such moves.
Update the program itself with `pipx upgrade lipi`.

```bash
lipi check            # before committing; --staged adds drift checks for staged changes
lipi audit            # before and after a complex or consequential task
lipi index            # after changing a workflow document's header
```

Run `lipi check` before committing. Fix or report errors introduced by your change. The user decides what to do with existing errors.

Address each warning by correcting it or explaining why no change is needed.
For A4, if the documentation still holds, read both regions in full and
confirm the pair in a second call:

```bash
lipi review "docs/api.md#retry" --at "src/retry.py:12" --full
lipi review "docs/api.md#retry" --at "src/retry.py:12" --confirm TOKEN --by "agent" --reason "The section still matches the code"
```
 Commit `.agents/lipi/reviews.json`.
Editing a reviewed region invalidates the review mark. Edit documentation
for substance. Review marks do not suppress T2 or checks for `covers`.
Unknown keys, wrong types, and invalid setting values stop the checker with
exit code 2. If the checker reports missing fingerprints in the lock file,
run `lipi init`. If a managed file differs from its fingerprint, take any
proposed rule change to lipi as an issue.

## Changing the rules <a id="rule-change"></a>

A rule applies if the checker enforces it or these rules state it.

1. Describe the friction in one sentence with an example.
2. Find out how many documents the change affects.
3. Change the rule, checker, and existing documents in a single commit.
4. Address every mismatch by updating the document or revisiting the rule.
