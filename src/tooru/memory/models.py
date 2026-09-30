from enum import StrEnum

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
    NOTE = "note"
    INSTRUCTION = "instruction"
    RELATIONSHIP = "relationship"
    SUMMARY = "summary"


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
    device_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    client_mutation_id: str | None = Field(default=None, max_length=200)


class MemoryItem(MemoryCreate):
    id: str
    revision: int = Field(ge=1)
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
    limit: int = Field(default=20, ge=1, le=100)


class MemorySyncRequest(ScopedMemoryModel):
    cursor_updated_at: str | None = None
    cursor_id: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class MemorySyncResponse(BaseModel):
    items: list[MemoryItem]
    next_updated_at: str | None = None
    next_id: str | None = None
    has_more: bool = False
