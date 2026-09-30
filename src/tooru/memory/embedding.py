import hashlib
import json
import math
import re
from typing import Protocol
from urllib.request import Request, urlopen


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Offline deterministic embedding fallback."""

    name = "hash"

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions
        self.model = f"hash-{dimensions}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = " ".join(text.lower().split())
        words = re.findall(r"[\w-]+", normalized, flags=re.UNICODE)
        features = words + [
            normalized[i : i + 3]
            for i in range(max(0, len(normalized) - 2))
            if not normalized[i : i + 3].isspace()
        ]

        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            sign = 1.0 if (value >> 8) & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class OpenAICompatibleEmbeddingProvider:
    """Embedding client for OpenAI-compatible /embeddings endpoints."""

    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int = 1024,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self.model, "input": texts},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))

        ordered = sorted(body["data"], key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in ordered]
        if vectors:
            self.dimensions = len(vectors[0])
        return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def build_embedding_provider(settings) -> EmbeddingProvider:
    provider = settings.memory_embedding_provider.lower().strip()
    if provider == "hash":
        return HashEmbeddingProvider(settings.memory_embedding_dimensions)

    if provider == "openai_compatible":
        missing = [
            name
            for name, value in {
                "TOORU_MEMORY_EMBEDDING_URL": settings.memory_embedding_url,
                "TOORU_MEMORY_EMBEDDING_API_KEY": settings.memory_embedding_api_key,
                "TOORU_MEMORY_EMBEDDING_MODEL": settings.memory_embedding_model,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing embedding configuration: " + ", ".join(missing)
            )
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.memory_embedding_url,
            api_key=settings.memory_embedding_api_key,
            model=settings.memory_embedding_model,
            dimensions=settings.memory_embedding_dimensions,
        )

    raise ValueError(f"Unsupported memory embedding provider: {provider}")
