# Where to start

| Task | Start here |
| --- | --- |
| Set up lipi in a project | [Setup guide](SETUP.md) |
| Use commands or change project settings | [Commands](docs/en/commands.md) and [settings](docs/en/settings.md) |
| Understand the rules and their rationale | [Rules](docs/en/rules.md) |
| Change lipi itself | Development instructions in [English](.agents/README.md) or [русский](.agents/ru/README.md) |

Read the sections relevant to your task. Both [English](docs/en/README.md) and [Russian](docs/ru/README.md) documentation are available.
Follow the [managed lipi rules](.agents/lipi/README.md) when editing documentation and workflow files.

## Verification and reflection <a id="verification-and-reflection"></a>

- For wording changes in documentation or contributor instructions, run `lipi check` and
  `lipi audit`. If a test checks an edited example, run that test too.
- For wording changes in managed templates, also run `lipi init` and verify that a
  subsequent `lipi init --dry-run` proposes no changes.
- For behavior changes, run tests for the affected commands and their callers. Widen the
  run if shared code could affect other commands. Run `lipi index` when workflow headers change.
- Run the full suite (`python3 -m unittest discover -s tests`) at agreed checkpoints and
  in both English and Russian before tagging. Count each language's passing run on the
  same tree. If only the release date, work item statuses or results, or the generated
  workflow index have changed since that run, it still counts. For those changes, run
  `lipi check`, `lipi audit`, and `python3 -m unittest tests.test_release`.

Occasionally look back at how a task went. If a step wasted time or a check missed a
problem, tell the user what happened and discuss one concrete improvement before adopting it.
