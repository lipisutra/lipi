# После включения workflow неясно, как завести мастер-план

- Created: 2026-11-27
- Updated: 2026-11-27
- Status: open
- Kind: friction

## Observation

В Lipi 1.4.1 можно сначала подключить только описание, а позже включить рабочие материалы. Повторный `init` создаёт указатели и возвращает 0. Если мастер-плана нет, вывод ничего не говорит о том, где его завести. [Порядок повторного init](../../../docs/ru/commands.md#update), [ADR-014](../../adr/adr-014-edinaya-komanda-init-primenyaet-ustanovlennyy-lipi.md).

## Воспроизведение

В пустом временном каталоге выполнить:

```sh
git init -q
mkdir docs
printf '# Guide\n' > docs/README.md
printf '# Agent\n\n[Lipi](.agents/lipi/README.md)\n' > AGENTS.md
printf '{"workflow":null}\n' > lipi.json
lipi init
printf '{"workflow":"workflow"}\n' > lipi.json
lipi init --dry-run
lipi init
```

Появляются `workflow/INDEX.md` и пять списков в `workflow/index/`. Файл `workflow/masterplan.md` отсутствует, `lipi check` возвращает 0.

## Критерии приёмки

- При таком подключении в `--dry-run` и при применении видно следующее действие. Для пустого каталога подсказка указывает, где и как вручную завести мастер-план. Для существующих рабочих материалов она указывает, как посмотреть [план переноса](../../../docs/ru/commands.md#migrate) до записи.
- Путь мастер-плана в подсказке учитывает настроенный каталог. Существующий мастер-план сохраняется, при его наличии подсказка о создании не нужна. Повторный `init` не восстанавливает удалённые пользователем заготовки.
