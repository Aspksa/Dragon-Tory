from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class InsightSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InsightStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReasoningPolicy(BaseModel):
    version: int = Field(default=1, ge=1)
    sample_count: int = Field(default=0, ge=0)
    hybrid_complexity_threshold: float = Field(default=0.42, ge=0.30, le=0.60)
    tree_complexity_threshold: float = Field(default=0.74, ge=0.60, le=0.88)
    hybrid_uncertainty_threshold: float = Field(default=0.30, ge=0.20, le=0.50)
    tree_uncertainty_threshold: float = Field(default=0.55, ge=0.40, le=0.75)
    verifier_escalation_score: float = Field(default=0.82, ge=0.72, le=0.92)
    verifier_escalation_uncertainty: float = Field(default=0.35, ge=0.20, le=0.55)
    updated_at: str | None = None
    reason: str = "default"


class MetacognitiveAssessment(BaseModel):
    readiness: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    contradiction_pressure: float = Field(ge=0.0, le=1.0)
    should_escalate: bool = False
    reasons: list[str] = Field(default_factory=list, max_length=12)


class ReasoningExperience(BaseModel):
    id: str
    created_at: str
    task_bucket: str
    mode: str
    complexity: float = Field(ge=0.0, le=1.0)
    memory_uncertainty: float = Field(ge=0.0, le=1.0)
    contradiction_count: int = Field(ge=0)
    verifier_score: float | None = Field(default=None, ge=0.0, le=1.0)
    verifier_uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    passed: bool | None = None
    escalated: bool = False
    ai_calls: int = Field(default=1, ge=1)
    duration_ms: float = Field(default=0.0, ge=0.0)
    user_feedback: str | None = None
    feedback_note: str | None = None


class ProactiveInsight(BaseModel):
    id: str
    rule_id: str
    severity: InsightSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    summary: str
    fingerprint: str
    status: InsightStatus = InsightStatus.OPEN
    entity_refs: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[dict] = Field(default_factory=list, max_length=50)
    first_seen_at: str
    last_seen_at: str
    resolved_at: str | None = None


class GraphNode(BaseModel):
    id: str
    kind: str
    label: str
    ref_id: str
    attributes: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    kind: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[dict] = Field(default_factory=list)


class CognitionStatus(BaseModel):
    policy: ReasoningPolicy
    experiences: int = 0
    open_insights: int = 0
    high_insights: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    last_cycle_at: str | None = None
    automation_running: bool = False
