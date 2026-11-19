# HTML-ссылки не видны mv и check

- Created: 2026-11-19
- Updated: 2026-11-19
- Status: closed
- Closed: 2026-11-19
- Result: Проверка и перенос учитывают адреса HTML-ссылок и изображений. План упоминает архив только при его наличии.
- Kind: bug

## Observation

lipi разбирает только Markdown-ссылки. Ссылки в HTML-тегах внутри
Markdown (`<img src>`, `<a href>`) для него не существуют:

- `lipi mv` не обновляет их и не показывает в плане;
- `lipi check` не замечает, что такая ссылка ведёт в никуда.

Ошибка остаётся молча. Сообщение «Unknown external links cannot be
detected» здесь сбивает с толку: ссылка внутренняя.

HTML-тег — обычный способ вставить картинку с размером или выравниванием,
например логотип в README.

Попутно: `lipi mv` всегда сообщает «history/ was excluded…», даже когда
папки `history/` в проекте нет.

## How to reproduce or where it occurred

При переносе логотипа `docs/ru/assets` → `docs/assets` командой
`lipi mv docs/ru/assets docs/assets --apply`. Ссылка в корневом
`README.md` (`<p align="center"><img src="docs/ru/assets/logo.png" …>`)
осталась старой. Подстановка несуществующего пути в тот же тег даёт
`lipi check` без ошибок. Та же ссылка в виде `![lipi](docs/assets/logo.png)`
обновляется правильно.
