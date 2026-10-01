from types import SimpleNamespace

import pytest

from tooru.chat.pipeline import ChatPipeline
from tooru.memory.models import ConversationMessage, MemoryKind


class FakeEvidenceStore:
    def __init__(self) -> None:
        self.items = []

    def add_evidence(self, memory_id, evidence, *, owner_id="local-user"):
        self.items.append((memory_id, evidence, owner_id))
        return evidence


class FakeMemory:
    def __init__(self) -> None:
        self.store = FakeEvidenceStore()


class FakeGuardian:
    def __init__(self) -> None:
        self.episode = None
        self.requests = []

    async def process(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            applied=[],
            pending_count=0,
            blocked_count=0,
        )

    def ingest_structured(self, memory, *, reason, auto_apply):
        self.episode = memory
        return SimpleNamespace(memory_id="episode-1", queue_id=None)


class FakeRouter:
    def __init__(self) -> None:
        self.request = None

    async def generate(self, provider, request, *, module, operation):
        self.request = request
        return SimpleNamespace(
            text="Краткая сводка проекта.",
            provider=provider,
            model="fake-model",
        )


@pytest.mark.asyncio
async def test_chat_outcome_becomes_project_episode_with_evidence() -> None:
    memory = FakeMemory()
    guardian = FakeGuardian()
    pipeline = ChatPipeline(
        memory=memory,
        router=object(),
        guardian=guardian,
    )

    status = await pipeline._remember(
        user_message="В проект Тоору добавь новую память.",
        assistant_answer="Готово: память добавлена и проверена.",
        remember=True,
        session_id="chat-123",
    )

    assert guardian.episode is not None
    assert guardian.episode.kind is MemoryKind.EPISODE
    assert guardian.episode.session_id == "chat-123"
    assert guardian.episode.source_ref == "chat:chat-123"
    assert "Задача пользователя" in guardian.episode.content
    assert "Результат Тоору" in guardian.episode.content
    assert memory.store.items[0][0] == "episode-1"
    assert memory.store.items[0][1].source_type == "chat"
    assert "episode:applied=1" in status


@pytest.mark.asyncio
async def test_conversation_summary_uses_previous_summary_and_new_batch() -> None:
    router = FakeRouter()
    pipeline = ChatPipeline(
        memory=FakeMemory(),
        router=router,
        guardian=FakeGuardian(),
    )

    summary = await pipeline.summarize_conversation(
        existing_summary="Решили усилить память.",
        messages=[
            ConversationMessage(
                role="user",
                content="Добавь временные факты.",
            ),
            ConversationMessage(
                role="assistant",
                content="Добавлены valid_from и valid_to.",
            ),
        ],
    )

    assert summary == "Краткая сводка проекта."
    assert router.request is not None
    payload = router.request.messages[0]["content"]
    assert "Решили усилить память." in payload
    assert "Добавь временные факты." in payload
