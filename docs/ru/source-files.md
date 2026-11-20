# Исходные файлы Lipi

Для разработки Lipi выполните `pipx install --editable .` из клона.
Команду можно запустить напрямую из исходников, например
`python3 src/lipi/cli.py check`.

- [src/lipi/cli.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/cli.py) принимает команду `lipi` и вызывает её обработчик.
- [src/lipi/init.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/init.py) разворачивает и обновляет Lipi в проекте.
- [src/lipi/check.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/check.py) запускает проверки на Python 3.9+ со стандартной библиотекой.
- В [src/lipi/checker/](https://github.com/lipisutra/lipi/tree/v1.0.0/src/lipi/checker/) находятся модули проверок из таблицы ниже.
- [src/lipi/sources.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/sources.py) определяет область чтения и состояние Git у подключённых репозиториев.
- [src/lipi/collect.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/collect.py) собирает из проектов замечания, адресованные Lipi.
- [src/lipi/migrate.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/migrate.py) переводит рабочие материалы существующего проекта в формат Lipi.
- [src/lipi/doctor.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/doctor.py) проверяет версию, состояние хука, указателей и базовой линии.
- [src/lipi/slice.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/slice.py) запускает срез. В `slice_index.py` собираются связи, в `slice_query.py` отбираются связанные места и документы, в `slice_diff.py` читается дифф Git, а в `slice_output.py` применяется предел вывода и формируется текст.
- [src/lipi/map.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/map.py) строит карту прямых меток по общему индексу.
- [src/lipi/repo_index.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/repo_index.py) индексирует прямые подключения. В `repo_slice.py` собирается срез с данными соседей, в `repo_output.py` — сведения об источниках и охвате.
- [src/lipi/locale/en/templates/](https://github.com/lipisutra/lipi/tree/v1.0.0/src/lipi/locale/en/templates/) содержит управляемые правила для `.agents/lipi/` и заготовки проекта в `seed/`.
- [pyproject.toml](https://github.com/lipisutra/lipi/blob/v1.0.0/pyproject.toml) описывает пакет и установку команды.
- В [CHANGELOG.md](../../CHANGELOG.md) записаны изменения по версиям.

## Модули проверок <a id="checker"></a>

| Модуль в `src/lipi/checker/` | Назначение |
| --- | --- |
| `conventions.py`, `config.py` | Соглашения формата, настройки и схемы состояния |
| `model.py` | Страницы Markdown, модель проекта и отбор файлов |
| `report.py` | Находки, уровни и форматы вывода |
| `docs.py`, `workflow.py` | Документация, языковые редакции и рабочие материалы |
| `trace.py`, `audit.py` | Метки, расхождения и аудит по истории Git |
| `targets.py` | Определение целей `@trace` и `covers` по разделу или номеру работы |
| `history.py` | История областей кода с учётом переносов |
| `state.py` | Совместимость версий, управляемые файлы и базовая линия |
| `structure.py` | Граф ссылок и связи устаревших разделов |
| `commands.py`, `runner.py` | Операции команд и порядок запуска проверок |

[src/lipi/__init__.py](https://github.com/lipisutra/lipi/blob/v1.0.0/src/lipi/__init__.py) задаёт общую версию правил, заготовок и программы.
