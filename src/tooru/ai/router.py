from tooru.ai.base import AIProvider, AIRequest, AIResponse


class AIRouter:
    """Routes requests without coupling Tooru memory to any single AI vendor."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider

    async def generate(self, provider_name: str, request: AIRequest) -> AIResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LookupError(f"AI provider is not registered: {provider_name}")
        return await provider.generate(request)
