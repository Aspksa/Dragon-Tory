from __future__ import annotations

import re

from tooru.memory.models import MemoryRetrievalStrategy, MemorySearch

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_EXACT_RE = re.compile(
    r"(?:\b[A-HJ-NPR-Z0-9]{17}\b|№\s*[\w./-]+|\b[A-ZА-Я0-9]{2,}[-/]\d+[\w./-]*\b)",
    re.IGNORECASE,
)
_CAUSAL_RE = re.compile(
    r"(?i)\b(?:почему|причин|из-за|следств|вызвал|повлек|cause|why|reason|resulted)\w*\b"
)
_TEMPORAL_RE = re.compile(
    r"(?i)\b(?:когда|на\s+дату|в\s+период|раньше|позже|до\s+этого|после\s+этого|"
    r"истор|действовал|актуал|сейчас|тогда|when|before|after|current|histor)\w*\b"
)
_GRAPH_RE = re.compile(
    r"(?i)\b(?:связан|связь|кто\s+закреп|водител|контрагент|относится|"
    r"принадлежит|зависит|related|linked|depends)\w*\b"
)
_SEMANTIC_RE = re.compile(
    r"(?i)\b(?:похож|аналог|смысл|пример|подобн|similar|analogy|meaning)\w*\b"
)


def select_retrieval_strategy(request: MemorySearch) -> MemoryRetrievalStrategy:
    if request.strategy is not MemoryRetrievalStrategy.AUTO:
        return request.strategy

    query = request.query.strip()
    if request.as_of or _TEMPORAL_RE.search(query) or _YEAR_RE.search(query):
        return MemoryRetrievalStrategy.TEMPORAL
    if _CAUSAL_RE.search(query):
        return MemoryRetrievalStrategy.CAUSAL
    if _EXACT_RE.search(query):
        return MemoryRetrievalStrategy.LEXICAL
    if _GRAPH_RE.search(query):
        return MemoryRetrievalStrategy.GRAPH

    token_count = len(re.findall(r"[\w-]+", query, flags=re.UNICODE))
    if _SEMANTIC_RE.search(query) or token_count >= 14:
        return MemoryRetrievalStrategy.SEMANTIC
    return MemoryRetrievalStrategy.BALANCED
