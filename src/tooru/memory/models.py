from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class MemoryScope(StrEnum):
    PERSONAL = "personal"
    PROJECT = "project"


class MemoryCreate(BaseModel):
    scope: MemoryScope
    content: str = Field(min_length=1, max_length=100_000)
    key: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)
    source: str = Field(default="user", max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_scope(self) -> "MemoryCreate":
        if self.scope is MemoryScope.PROJECT and not self.project_id:
            raise ValueError("project_id is required for project memory")
        if self.scope is MemoryScope.PERSONAL and self.project_id is not None:
            raise ValueError("personal memory cannot have project_id")
        return self


class MemoryItem(MemoryCreate):
    id: str
    created_at: str
    updated_at: str


class MemorySearch(BaseModel):
    scope: MemoryScope
    query: str = Field(min_length=1, max_length=2_000)
    project_id: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_scope(self) -> "MemorySearch":
        if self.scope is MemoryScope.PROJECT and not self.project_id:
            raise ValueError("project_id is required for project memory search")
        if self.scope is MemoryScope.PERSONAL and self.project_id is not None:
            raise ValueError("personal memory search cannot have project_id")
        return self
