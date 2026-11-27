# Базовая линия скрывает V2 при первом подключении

- Created: 2026-11-27
- Updated: 2026-11-27
- Status: open
- Kind: bug

## Observation

В Lipi 1.4.1 первый `init` просит вручную добавить в существующий `AGENTS.md` ссылку на правила. Если её пропустить, обычный `check` всё равно завершается с кодом 0. Причина видна через `--no-baseline`: только что возникшая V2 уже попала в базовую линию как прежний долг. [Проверка V2](../../../docs/ru/codes.md#v2), [решение о базовой линии](../../adr/adr-003-bazovaya-liniya-dlya-suschestvuyuschego-dolga.md).

## Воспроизведение

В пустом временном каталоге выполнить:

```sh
git init -q
mkdir docs
printf '# Guide\n' > docs/README.md
printf '# Agent\n' > AGENTS.md
printf '{"workflow":null}\n' > lipi.json
lipi init
lipi check --format json
lipi check --no-baseline --format json
```

У первого `check` код 0 и `baseline.known = 1`. Второй возвращает 1 и показывает единственную ошибку V2 в `AGENTS.md`.

## Критерии приёмки

- Пока V2 имеет уровень ошибки и ссылка отсутствует, обычный `lipi check` показывает V2 и возвращает 1. Это верно и для проекта с записью V2 в прежней базовой линии.
- В том же примере после добавления ссылки на `.agents/lipi/README.md` проверка возвращает 0. Ручная чистка baseline для этого не требуется.
- Настроенный уровень V2 сохраняется. Вопрос касается только V2.
