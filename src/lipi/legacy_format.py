"""Служебные строки прежнего формата для импорта и чтения истории."""

from .checker.conventions import (
    DECISION_HEADING, K_ADDRESSEE, K_DUE, K_REFINES, K_SOURCE, K_STATUS,
)


LEGACY_FIELDS = {
    "статус": K_STATUS,
    "адресат": K_ADDRESSEE,
    "источник": K_SOURCE,
    "уточняет": K_REFINES,
    "срок": K_DUE,
}

LEGACY_STATUSES = {
    "новый": "new",
    "в работе": "in progress",
    "на приемке": "pending acceptance",
    "отложен": "deferred",
    "завершен": "completed",
    "отменен": "canceled",
    "открыто": "open",
    "закрыто": "closed",
    "предложено": "proposed",
    "принято": "accepted",
    "заменено": "superseded",
    "отклонено": "rejected",
}

LEGACY_KINDS = {
    "баг": "bug",
    "трение": "friction",
    "запрос": "request",
    "вопрос": "question",
}

LEGACY_SECTIONS = {
    "pln": {"Зачем": "Purpose", "Критерии завершения": "Completion criteria"},
    "iss": {"Что наблюдается": "Observation"},
    "adr": {"Решение": DECISION_HEADING},
}


LEGACY_SOURCE_EXTERNAL = "внешний"


def historical_status(header):
    """Статус из канонической или прежней шапки, записанной в Git."""
    if K_STATUS in header:
        return header[K_STATUS].strip("* .").lower()
    for key, value in header.items():
        if LEGACY_FIELDS.get(key.casefold()) == K_STATUS:
            return LEGACY_STATUSES.get(value.strip("* .").lower().replace("ё", "е"), "")
    return ""
