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

    message, history = store.retry_context(chat_id)
    assert message == "Последний вопрос"
    assert [item["content"] for item in history] == [
        "Первый вопрос",
        "Первый ответ",
    ]
    assert [item["content"] for item in store.messages(chat_id)] == [
        "Первый вопрос",
        "Первый ответ",
        "Последний вопрос",
    ]

    store.delete(chat_id)
    assert store.list() == []
