import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from tooru.ai.anthropic_provider import AnthropicProvider
from tooru.ai.base import AIRequest
from tooru.ai.openai_compatible import OpenAICompatibleProvider

router = APIRouter(prefix="/v1/settings", tags=["settings"])


class DeepSeekSettingsUpdate(BaseModel):
    api_key: str = Field(min_length=8, max_length=2_000)
    base_url: str = Field(
        default="https://foundation-models.api.cloud.ru/v1",
        min_length=8,
        max_length=500,
    )
    model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash",
        min_length=1,
        max_length=300,
    )


class DeepSeekSettingsStatus(BaseModel):
    configured: bool
    registered: bool
    base_url: str
    model: str


class ClaudeSettingsUpdate(BaseModel):
    api_key: str = Field(min_length=8, max_length=2_000)
    model: str = Field(
        default="claude-sonnet-5-5",
        min_length=1,
        max_length=300,
    )


class ClaudeSettingsStatus(BaseModel):
    configured: bool
    registered: bool
    model: str


class AITestResult(BaseModel):
    ok: bool
    provider: str
    model: str
    response: str


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Настройки можно изменять только с локального компьютера.",
        )


def _quote_env(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_env_values(path: Path, values: dict[str, str]) -> None:
    existing: list[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        replaced = False
        for key in list(remaining):
            if stripped.startswith(f"{key}="):
                output.append(
                    f"{key}={_quote_env(remaining.pop(key))}"
                )
                replaced = True
                break
        if not replaced:
            output.append(line)

    if output and output[-1].strip():
        output.append("")
    for key, value in remaining.items():
        output.append(f"{key}={_quote_env(value)}")

    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(temp, path)


@router.get(
    "/ai/deepseek",
    response_model=DeepSeekSettingsStatus,
)
def get_deepseek_settings(
    request: Request,
) -> DeepSeekSettingsStatus:
    config = request.app.state.deepseek_config
    return DeepSeekSettingsStatus(
        configured=config["configured"],
        registered=request.app.state.ai_router.has_provider("deepseek"),
        base_url=config["base_url"],
        model=config["model"],
    )


@router.post(
    "/ai/deepseek",
    response_model=DeepSeekSettingsStatus,
)
def save_deepseek_settings(
    payload: DeepSeekSettingsUpdate,
    request: Request,
) -> DeepSeekSettingsStatus:
    _require_local(request)

    if not payload.base_url.lower().startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Адрес API должен использовать HTTPS.",
        )

    _write_env_values(
        Path(".env").resolve(),
        {
            "TOORU_DEEPSEEK_API_KEY": payload.api_key,
            "TOORU_DEEPSEEK_BASE_URL": payload.base_url.rstrip("/"),
            "TOORU_DEEPSEEK_MODEL": payload.model,
        },
    )
    request.app.state.ai_router.register(
        OpenAICompatibleProvider(
            name="deepseek",
            api_key=payload.api_key,
            base_url=payload.base_url,
            model=payload.model,
        )
    )
    request.app.state.deepseek_config = {
        "configured": True,
        "base_url": payload.base_url.rstrip("/"),
        "model": payload.model,
    }
    return get_deepseek_settings(request)


@router.post(
    "/ai/deepseek/test",
    response_model=AITestResult,
)
async def test_deepseek(request: Request) -> AITestResult:
    _require_local(request)
    return await _test_provider(request, "deepseek")


@router.get(
    "/ai/claude",
    response_model=ClaudeSettingsStatus,
)
def get_claude_settings(request: Request) -> ClaudeSettingsStatus:
    config = request.app.state.claude_config
    return ClaudeSettingsStatus(
        configured=config["configured"],
        registered=request.app.state.ai_router.has_provider("claude"),
        model=config["model"],
    )


@router.post(
    "/ai/claude",
    response_model=ClaudeSettingsStatus,
)
def save_claude_settings(
    payload: ClaudeSettingsUpdate,
    request: Request,
) -> ClaudeSettingsStatus:
    _require_local(request)

    _write_env_values(
        Path(".env").resolve(),
        {
            "TOORU_CLAUDE_API_KEY": payload.api_key,
            "TOORU_CLAUDE_MODEL": payload.model,
        },
    )
    request.app.state.ai_router.register(
        AnthropicProvider(
            api_key=payload.api_key,
            model=payload.model,
        )
    )
    request.app.state.claude_config = {
        "configured": True,
        "model": payload.model,
    }
    return get_claude_settings(request)


@router.post(
    "/ai/claude/test",
    response_model=AITestResult,
)
async def test_claude(request: Request) -> AITestResult:
    _require_local(request)
    return await _test_provider(request, "claude")


async def _test_provider(
    request: Request,
    provider_name: str,
) -> AITestResult:
    router_state = request.app.state.ai_router
    if not router_state.has_provider(provider_name):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Провайдер {provider_name} не настроен.",
        )

    try:
        result = await router_state.generate(
            provider_name,
            AIRequest(
                system_prompt="Это проверка API. Ответь кратко: OK.",
                messages=[
                    {
                        "role": "user",
                        "content": "Проверка соединения.",
                    }
                ],
                max_tokens=32,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Ошибка API {provider_name}: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return AITestResult(
        ok=True,
        provider=result.provider,
        model=result.model,
        response=result.text[:500],
    )
