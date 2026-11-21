# lipi check без lipi.json создаёт указатель в существующей workflow/

- Created: 2026-11-21
- Updated: 2026-11-21
- Status: in progress
- Kind: bug

## Observation

В версии 1.3.0 локальный `lipi check` в репозитории без `lipi.json` создаёт шесть файлов: `workflow/INDEX.md` и пять списков в `workflow/index/`. Достаточно существующего каталога `workflow/` с обычной заметкой. На этом примере команда завершается с кодом 0, а в Git появляются неотслеживаемые файлы.

## How to reproduce or where it occurred

В пустом временном каталоге, вне CI:

```sh
git init -q
mkdir workflow
printf '# Notes\n' > workflow/notes.md
git add workflow/notes.md
git -c user.name=Test -c user.email=test@example.invalid commit -qm Initial
lipi check
git status --porcelain --untracked-files=all
```

## Acceptance criteria

- Без файла настроек `check` и `audit` пропускают чужую `workflow/`. В примере выше код выхода 2 и подсказка `lipi init`; дерево остаётся чистым.
- Если есть `docs/`, проверяются документы с обычным результатом и текстовой подсказкой. Без настроек `new`, `index` и [`baseline`](../../../docs/ru/commands.md#baseline) (включая `--prune`) возвращают код 2 с подсказкой `lipi init` и ничего не записывают. `slice` и `map` сохраняют дерево, запись через `review` не создаёт указатель.
- Пустой объект в `lipi.json` и явно переданный файл `--config` подключают стандартный каталог рабочих материалов.
