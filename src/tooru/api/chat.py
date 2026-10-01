from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from tooru.ai.base import AIRequest
from tooru.memory.models import (
    ConversationMessage,
    MemoryContextRequest,
    MemoryGuardianRequest,
    MemoryScope,
)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    project_id: str | None = Field(default="dragon-tory", max_length=200)
    provider: str = Field(default="deepseek", max_length=100)
    remember: bool = True
    history: list[ConversationMessage] = Field(default_factory=list, max_length=40)


class ChatResponse(BaseModel):
    answer: str
    provider: str
    model: str
    context_memories: int
    memory_status: str


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    router_state = request.app.state.ai_router
    if not router_state.has_provider(payload.provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"AI provider '{payload.provider}' is not configured. "
                "Open Settings and save the API key."
            ),
        )

    context = request.app.state.memory.context_pack(
        MemoryContextRequest(
            owner_id="local-user",
            query=payload.message,
            project_id=payload.project_id,
            include_personal=True,
            personal_limit=8,
            project_limit=12 if payload.project_id else 0,
            max_chars=12_000,
        )
    )

    messages = [
        {"role": item.role, "content": item.content}
        for item in payload.history[-20:]
        if item.role in {"user", "assistant"}
    ]
    messages.append({"role": "user", "content": payload.message})

    system_prompt = (
        "Ты Дракончик Тоору — локальный персональный AI-помощник. "
        "Отвечай на русском языке, если пользователь не попросил иначе. "
        "Используй память ниже как контекст; не выдумывай отсутствующие факты.\n\n"
        + context.rendered_context
    )

    try:
        ai_response = await router_state.generate(
            payload.provider,
            AIRequest(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=2_000,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI provider error: {type(exc).__name__}: {exc}",
        ) from exc

    memory_status = "disabled"
    if payload.remember:
        try:
            scope = (
                MemoryScope.PROJECT
                if payload.project_id
                else MemoryScope.PERSONAL
            )
            guardian_result = await request.app.state.memory_guardian.process(
                MemoryGuardianRequest(
                    owner_id="local-user",
                    scope=scope,
                    project_id=payload.project_id,
                    messages=[
                        ConversationMessage(role="user", content=payload.message),
                        ConversationMessage(
                            role="assistant",
                            content=ai_response.text,
                        ),
                    ],
                    auto_apply=True,
                    use_ai=True,
                    primary_provider=payload.provider,
                )
            )
            memory_status = (
                f"applied={len(guardian_result.applied)}, "
                f"pending={guardian_result.pending_count}, "
                f"blocked={guardian_result.blocked_count}"
            )
        except Exception as exc:
            memory_status = f"memory-error:{type(exc).__name__}"

    return ChatResponse(
        answer=ai_response.text,
        provider=ai_response.provider,
        model=ai_response.model,
        context_memories=context.total_memories,
        memory_status=memory_status,
    )
