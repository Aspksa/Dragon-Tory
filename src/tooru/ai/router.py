from tooru.ai.base import AIProvider, AIRequest, AIResponse


class AIRouter:
    """Routes requests without coupling Tooru memory to any single AI vendor."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider

    def has_provider(self, provider_name: str) -> bool:
        return provider_name in self._providers

    def available_providers(self) -> list[str]:
        return sorted(self._providers)

    async def generate(self, provider_name: str, request: AIRequest) -> AIResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LookupError(f"AI provider is not registered: {provider_name}")
        return await provider.generate(request)
