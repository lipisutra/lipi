# Where to start

| Task | Start here |
| --- | --- |
| Set up lipi in a project | [Setup guide](SETUP.md) |
| Use commands or change project settings | [Commands](docs/en/commands.md) and [settings](docs/en/settings.md) |
| Understand the rules and their rationale | [Rules](docs/en/rules.md) |
| Change lipi itself | Development instructions in [English](.agents/README.md) or [русский](.agents/ru/README.md) |
| Propose a field, relationship, or attribute that authors enter by hand | [Design questions for manual input](.agents/README.md#manual-input) |

Read the sections relevant to your task. Both [English](docs/en/README.md) and [Russian](docs/ru/README.md) documentation are available.
Follow the [managed lipi rules](.agents/lipi/README.md) when editing documentation and workflow files.

Set an ADR to `accepted` only when the user explicitly accepts the decision.
Their approval to start a plan moves it to `in progress`. Set it to `completed`
only when they explicitly accept the result.

## Verification and reflection <a id="verification-and-reflection"></a>

- For wording changes in documentation or contributor instructions, run `lipi check` and
  `lipi audit`. If a test checks an edited example, run that test too.
- For wording changes in managed templates, also run `lipi init` and verify that a
  subsequent `lipi init --dry-run` proposes no changes.
- During development, test the changed behavior and the commands that use it. Check
  changed messages in English and Russian. If you cannot identify all affected commands,
  consider an early full run. Run `lipi index` when workflow headers change.
- When a change promises to preserve existing command output, compare text and JSON with
  the latest release tag on the same committed example with the new feature unused.
  A regression test that checks that case against output captured from the tag is sufficient.
- Create temporary test projects outside the clone. After the check, remove the files
  you created for the experiment and use `git worktree remove` for any worktree you created.
- The full suite (`python3 -m unittest discover -s tests`) is required only before tagging
  a release. Run it first in English, then in Russian, on the same tree, with one test
  group at a time. If only the release date, work item statuses or results, or the generated
  workflow index have changed since that run, it still counts. For those changes, run
  `lipi check`, `lipi audit`, and `python3 -m unittest tests.test_release`.

Occasionally look back at how a task went. If a step wasted time or a check missed a
problem, tell the user what happened and discuss one concrete improvement before adopting it.
