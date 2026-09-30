import re

from tooru.memory.models import (
    ConversationMessage,
    MemoryCreate,
    MemoryExtractRequest,
    MemoryKind,
)


class HeuristicMemoryExtractor:
    """Conservative offline extractor for durable memory candidates."""

    _rules = (
        (
            MemoryKind.GOAL,
            re.compile(
                r"\b(моя цель|цель проекта|хочу сделать|хочу чтобы|планирую|goal|plan to)\b",
                re.IGNORECASE,
            ),
            0.88,
        ),
        (
            MemoryKind.EPISODE,
            re.compile(
                r"\b(сегодня сделали|вчера сделали|мы сделали|завершили|починили|исправили|today we|yesterday we|completed|fixed)\b",
                re.IGNORECASE,
            ),
            0.72,
        ),
        (
            MemoryKind.RELATIONSHIP,
            re.compile(
                r"\b(связан с|относится к|зависит от|используется в|connected to|depends on|belongs to)\b",
                re.IGNORECASE,
            ),
            0.78,
        ),
        (
            MemoryKind.PREFERENCE,
            re.compile(
                r"\b(я предпочитаю|мне нравится|мне удобнее|предпочитаю|i prefer|i like)\b",
                re.IGNORECASE,
            ),
            0.75,
        ),
        (
            MemoryKind.DECISION,
            re.compile(
                r"\b(решили|фиксируем|будем использовать|выбрали|decision|we will use)\b",
                re.IGNORECASE,
            ),
            0.90,
        ),
        (
            MemoryKind.TASK,
            re.compile(
                r"\b(надо|нужно|сделай|добавить|исправить|todo|need to|must)\b",
                re.IGNORECASE,
            ),
            0.70,
        ),
        (
            MemoryKind.INSTRUCTION,
            re.compile(
                r"\b(всегда|никогда|правило|обязательно|always|never|rule)\b",
                re.IGNORECASE,
            ),
            0.85,
        ),
        (
            MemoryKind.FACT,
            re.compile(
                r"\b(у меня|мой|моя|моё|проект называется|использует|has|uses|is called)\b",
                re.IGNORECASE,
            ),
            0.65,
        ),
    )

    def extract(self, request: MemoryExtractRequest) -> list[MemoryCreate]:
        candidates: list[MemoryCreate] = []
        seen: set[str] = set()

        for message in request.messages:
            if message.role != "user":
                continue

            for sentence in self._sentences(message):
                normalized = " ".join(sentence.lower().split())
                if len(normalized) < 8 or normalized in seen:
                    continue

                for kind, pattern, importance in self._rules:
                    if not pattern.search(sentence):
                        continue

                    seen.add(normalized)
                    candidates.append(
                        MemoryCreate(
                            owner_id=request.owner_id,
                            scope=request.scope,
                            project_id=request.project_id,
                            kind=kind,
                            content=sentence.strip(),
                            source="conversation-extractor",
                            confidence=0.72,
                            importance=importance,
                            tags=["auto-extracted"],
                            device_id=request.device_id,
                            session_id=request.session_id,
                        )
                    )
                    break

        return candidates

    @staticmethod
    def _sentences(message: ConversationMessage) -> list[str]:
        return [
            part.strip()
            for part in re.split(r"(?<=[.!?。！？])\s+|\n+", message.content)
            if part.strip()
        ]
