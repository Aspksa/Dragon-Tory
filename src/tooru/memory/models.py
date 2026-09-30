from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class MemoryScope(StrEnum):
    PERSONAL = "personal"
    PROJECT = "project"


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    TASK = "task"
    EVENT = "event"
    EPISODE = "episode"
    GOAL = "goal"
    ENTITY = "entity"
    NOTE = "note"
    INSTRUCTION = "instruction"
    RELATIONSHIP = "relationship"
    SUMMARY = "summary"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class MemoryLinkType(StrEnum):
    RELATED = "related"
    DUPLICATE = "duplicate"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    SUMMARIZES = "summarizes"
    SUPPORTS = "supports"


class MemoryIntelligenceAction(StrEnum):
    IGNORE = "ignore"
    CREATE = "create"
    UPDATE = "update"


class ScopedMemoryModel(BaseModel):
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    scope: MemoryScope
    project_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope is MemoryScope.PROJECT and not self.project_id:
            raise ValueError("project_id is required for project memory")
        if self.scope is MemoryScope.PERSONAL and self.project_id is not None:
            raise ValueError("personal memory cannot have project_id")
        return self


class MemoryCreate(ScopedMemoryModel):
    kind: MemoryKind = MemoryKind.NOTE
    content: str = Field(min_length=1, max_length=100_000)
    key: str | None = Field(default=None, max_length=200)
    source: str = Field(default="user", max_length=100)
    source_ref: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=30)
    pinned: bool = False
    expires_at: str | None = None
    device_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    client_mutation_id: str | None = Field(default=None, max_length=200)


class MemoryItem(MemoryCreate):
    id: str
    status: MemoryStatus = MemoryStatus.ACTIVE
    revision: int = Field(ge=1)
    access_count: int = Field(default=0, ge=0)
    helpful_count: int = Field(default=0, ge=0)
    unhelpful_count: int = Field(default=0, ge=0)
    last_accessed_at: str | None = None
    reinforced_at: str | None = None
    archived_at: str | None = None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    kind: MemoryKind | None = None
    key: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=100)
    source_ref: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = Field(default=None, max_length=30)
    pinned: bool | None = None
    expires_at: str | None = None
    device_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    expected_revision: int = Field(ge=1)


class MemoryDelete(BaseModel):
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)
    device_id: str | None = Field(default=None, max_length=200)


class MemorySearch(ScopedMemoryModel):
    query: str = Field(min_length=1, max_length=2_000)
    kind: MemoryKind | None = None
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=10)
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class MemoryRecallHit(BaseModel):
    memory: MemoryItem
    score: float
    semantic_score: float
    lexical_score: float
    importance_score: float
    confidence_score: float
    recency_score: float
    usage_score: float
    pin_score: float


class MemoryContextRequest(BaseModel):
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2_000)
    project_id: str | None = Field(default=None, max_length=200)
    include_personal: bool = True
    personal_limit: int = Field(default=8, ge=0, le=50)
    project_limit: int = Field(default=12, ge=0, le=100)
    max_chars: int = Field(default=12_000, ge=1_000, le=100_000)


class MemoryContextPack(BaseModel):
    query: str
    project_id: str | None
    pinned_personal: list[MemoryItem]
    pinned_project: list[MemoryItem]
    personal_hits: list[MemoryRecallHit]
    project_hits: list[MemoryRecallHit]
    rendered_context: str
    total_memories: int


class MemoryFeedback(BaseModel):
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    helpful: bool
    strength: float = Field(default=1.0, ge=0.1, le=1.0)


class MemorySyncRequest(ScopedMemoryModel):
    cursor_updated_at: str | None = None
    cursor_id: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class MemorySyncResponse(BaseModel):
    items: list[MemoryItem]
    next_updated_at: str | None = None
    next_id: str | None = None
    has_more: bool = False


class ConversationMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant|system|tool)$")
    content: str = Field(min_length=1, max_length=100_000)


class MemoryExtractRequest(ScopedMemoryModel):
    messages: list[ConversationMessage] = Field(min_length=1, max_length=200)
    auto_save: bool = True
    device_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)


class MemoryExtractResponse(BaseModel):
    candidates: list[MemoryCreate]
    saved: list[MemoryItem]


class MemoryIntelligenceRequest(ScopedMemoryModel):
    messages: list[ConversationMessage] = Field(min_length=1, max_length=200)
    auto_apply: bool = True
    use_ai: bool = True
    primary_provider: str | None = Field(default=None, max_length=100)
    reviewer_provider: str | None = Field(default=None, max_length=100)
    device_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)


class MemoryIntelligenceDecision(BaseModel):
    action: MemoryIntelligenceAction
    content: str = Field(default="", max_length=100_000)
    kind: MemoryKind = MemoryKind.NOTE
    key: str | None = Field(default=None, max_length=200)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=30)
    target_memory_id: str | None = Field(default=None, max_length=200)
    reason: str = Field(default="", max_length=2_000)


class MemoryIntelligenceResult(BaseModel):
    analyzer: str
    reviewer: str | None = None
    used_fallback: bool = False
    decisions: list[MemoryIntelligenceDecision]
    applied: list[MemoryItem]
    ignored: int = 0


class MemoryConsolidateRequest(ScopedMemoryModel):
    limit: int = Field(default=100, ge=2, le=1000)
    min_importance: float = Field(default=0.25, ge=0.0, le=1.0)


class MemoryConsolidateResponse(BaseModel):
    summary: str
    memory: MemoryItem | None
    source_ids: list[str]


class MemoryLink(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation: MemoryLinkType
    weight: float = Field(ge=0.0, le=1.0)
    created_at: str


class MemoryRevision(BaseModel):
    memory_id: str
    revision: int
    reason: str
    snapshot: dict[str, Any]
    created_at: str


class MemoryMaintenanceReport(BaseModel):
    started_at: str
    completed_at: str
    vectors_reindexed: int = 0
    expired_archived: int = 0
    stale_archived: int = 0
    summaries_created: int = 0
    active_memories: int = 0
    archived_memories: int = 0
    superseded_memories: int = 0
