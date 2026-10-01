from pathlib import Path

from tooru.chat.store import ChatStore


def make_store(tmp_path: Path) -> ChatStore:
    store = ChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    return store


def test_chat_store_persists_and_searches(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    chat = store.create()
    chat_id = chat["id"]

    store.add_message(
        chat_id,
        role="user",
        content="Поговорим про память Тоору",
    )
    store.auto_title(chat_id, "Поговорим про память Тоору")
    store.add_message(
        chat_id,
        role="assistant",
        content="Конечно.",
    )

    loaded = store.get(chat_id)
    assert loaded["title"] == "Поговорим про память Тоору"
    assert loaded["message_count"] == 2
    assert len(store.messages(chat_id)) == 2

    results = store.list(query="память")
    assert [item["id"] for item in results] == [chat_id]


def test_chat_store_rename_delete_and_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    chat_id = store.create("Первый")["id"]
    store.add_message(chat_id, role="user", content="Первый вопрос")
    store.add_message(chat_id, role="assistant", content="Первый ответ")
    store.add_message(chat_id, role="user", content="Последний вопрос")
    store.add_message(chat_id, role="assistant", content="Старый ответ")

    renamed = store.rename(chat_id, "Новый заголовок")
    assert renamed["title"] == "Новый заголовок"

    message, history, sequence = store.retry_context(chat_id)
    assert message == "Последний вопрос"
    assert [item["content"] for item in history] == [
        "Первый вопрос",
        "Первый ответ",
    ]
    assert [item["content"] for item in store.messages(chat_id)] == [
        "Первый вопрос",
        "Первый ответ",
        "Последний вопрос",
        "Старый ответ",
    ]

    store.replace_after(
        chat_id,
        sequence=sequence,
        assistant_content="Новый ответ",
    )
    assert [item["content"] for item in store.messages(chat_id)] == [
        "Первый вопрос",
        "Первый ответ",
        "Последний вопрос",
        "Новый ответ",
    ]

    store.delete(chat_id)
    assert store.list() == []



def test_chat_history_survives_store_reopen(tmp_path: Path) -> None:
    path = tmp_path / "persistent.sqlite3"
    first = ChatStore(path)
    first.initialize()
    chat_id = first.create("Сохраняемый чат")["id"]
    first.add_message(chat_id, role="user", content="Сообщение")

    second = ChatStore(path)
    second.initialize()

    assert second.get(chat_id)["title"] == "Сохраняемый чат"
    assert second.messages(chat_id)[0]["content"] == "Сообщение"

def test_working_memory_summary_persists_and_retry_invalidates(tmp_path: Path) -> None:
    path = tmp_path / "working.sqlite3"
    store = ChatStore(path)
    store.initialize()
    chat_id = store.create("Длинный чат")["id"]
    for index in range(6):
        role = "user" if index % 2 == 0 else "assistant"
        store.add_message(
            chat_id,
            role=role,
            content=f"Сообщение {index}",
        )

    store.update_summary(
        chat_id,
        summary="Обсуждаем архитектуру памяти и следующий этап.",
        covered_messages=4,
    )
    working = store.working_memory(chat_id, recent_limit=2)
    assert working["summary"] == (
        "Обсуждаем архитектуру памяти и следующий этап."
    )
    assert working["summary_message_count"] == 4
    assert [item["content"] for item in working["recent_messages"]] == [
        "Сообщение 4",
        "Сообщение 5",
    ]

    reopened = ChatStore(path)
    reopened.initialize()
    assert reopened.get(chat_id)["summary_message_count"] == 4

    reopened.add_message(chat_id, role="user", content="Последний вопрос")
    reopened.add_message(chat_id, role="assistant", content="Старый ответ")
    _, _, sequence = reopened.retry_context(chat_id)
    reopened.replace_after(
        chat_id,
        sequence=sequence,
        assistant_content="Новый ответ",
    )
    refreshed = reopened.get(chat_id)
    assert refreshed["summary"] == ""
    assert refreshed["summary_message_count"] == 0
