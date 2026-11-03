import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app.graph import (
    LLMEmptyResponseError,
    LLMInvalidJSONError,
    get_async_graph,
)
from app.schemas import ApproveRequest, ProductCard, ProductInput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def card_to_markdown(card: ProductCard) -> str:
    specs_rows = "\n".join(f"| {k} | {v} |" for k, v in card.specifications.items())
    return "\n".join([
        f"# {card.title}",
        "",
        card.short_description,
        "",
        "## Коммерческий блок",
        card.commercial_block,
        "",
        "## Описание",
        card.seo_description,
        "",
        "## Ключевые особенности",
        *[f"- {f}" for f in card.key_features],
        "",
        "## Характеристики",
        "| Параметр | Значение |",
        "|---|---|",
        specs_rows,
        "",
        "## Применение",
        *[f"- {a}" for a in card.applications],
        "",
        "## Поисковые запросы",
        ", ".join(card.search_queries),
    ])


@router.post("/stream")
async def stream_draft(input_data: ProductInput):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator():
        yield _sse({"event": "started", "thread_id": thread_id})
        try:
            g = await get_async_graph()
            async for event in g.astream(
                {"raw_input": input_data.model_dump()},
                config=config, stream_mode="updates",
            ):
                for node_name in event.keys():
                    yield _sse({"event": "node", "node": node_name})

            state = await g.aget_state(config)
            draft = state.values.get("draft")
            validation_errors = state.values.get("validation_errors", [])

            if not draft and not state.next:
                message = (
                    "; ".join(validation_errors)
                    or "LLM не вернула валидный JSON. Проверьте модель и max_tokens."
                )
                yield _sse({"event": "error", "message": message})
                return

            payload = {
                "thread_id": thread_id,
                "draft": draft,
                "validation_errors": validation_errors,
                "missing_fields": state.values.get("missing_fields", []),
                "iteration": state.values.get("iteration", 0),
                "human_approved": state.values.get("human_approved", False),
            }
            yield _sse({"event": "awaiting_review" if state.next else "done", **payload})

        except LLMEmptyResponseError as exc:
            logger.warning("LLM empty response, thread_id=%s: %s", thread_id, exc)
            yield _sse({"event": "error", "message": str(exc)})
        except LLMInvalidJSONError as exc:
            logger.error("LLM invalid JSON, thread_id=%s: %s", thread_id, exc)
            yield _sse({"event": "error", "message": str(exc)})
        except AuthenticationError:
            logger.exception("LLM auth error, thread_id=%s", thread_id)
            yield _sse({"event": "error", "message": "Неверный API-ключ LLM."})
        except RateLimitError:
            logger.exception("LLM rate limit, thread_id=%s", thread_id)
            yield _sse({"event": "error", "message": "Превышен лимит запросов к LLM."})
        except (APITimeoutError, TimeoutError):
            logger.exception("LLM timeout, thread_id=%s", thread_id)
            yield _sse({"event": "error", "message": "LLM не ответила вовремя."})
        except APIConnectionError:
            logger.exception("LLM connection error, thread_id=%s", thread_id)
            yield _sse({
                "event": "error",
                "message": (
                    "Не удалось подключиться к LLM. Проверьте OPENAI_BASE_URL "
                    "и доступность провайдера."
                ),
            })
        except APIStatusError as exc:
            logger.exception("LLM HTTP error, thread_id=%s", thread_id)
            yield _sse({
                "event": "error",
                "message": f"LLM вернула HTTP {exc.status_code}: {exc.message}",
            })
        except Exception:
            logger.exception("stream_draft failed, thread_id=%s", thread_id)
            yield _sse({"event": "error", "message": "Внутренняя ошибка сервера."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/{thread_id}/resume")
async def resume_draft(thread_id: str, body: ApproveRequest):
    config = {"configurable": {"thread_id": thread_id}}
    g = await get_async_graph()

    state = await g.aget_state(config)
    if not state.values:
        raise HTTPException(404, "Сессия не найдена. Запустите генерацию заново.")
    if not state.next:
        raise HTTPException(400, "Граф уже завершён")

    try:
        await g.ainvoke(
            Command(resume={
                "approved": body.approved,
                "edited_draft": body.edited_draft.model_dump() if body.edited_draft else None,
                "feedback": body.feedback,
            }),
            config=config,
        )
    except LLMEmptyResponseError as exc:
        raise HTTPException(502, str(exc))
    except LLMInvalidJSONError as exc:
        raise HTTPException(502, str(exc))
    except AuthenticationError:
        raise HTTPException(502, "Ошибка авторизации LLM")
    except RateLimitError:
        raise HTTPException(503, "LLM перегружена, повторите позже")
    except (APITimeoutError, TimeoutError):
        raise HTTPException(504, "LLM не ответила вовремя")
    except APIConnectionError:
        raise HTTPException(
            502,
            "Не удалось подключиться к LLM. Проверьте OPENAI_BASE_URL и сеть.",
        )
    except APIStatusError as exc:
        raise HTTPException(502, f"LLM вернула HTTP {exc.status_code}: {exc.message}")

    final = await g.aget_state(config)
    return {
        "status": "awaiting_review" if final.next else "done",
        "draft": final.values.get("draft"),
        "human_approved": final.values.get("human_approved", False),
        "validation_errors": final.values.get("validation_errors", []),
        "missing_fields": final.values.get("missing_fields", []),
        "iteration": final.values.get("iteration", 0),
    }


@router.post("/export/markdown")
async def export_markdown(card: ProductCard):
    """Единственная реализация Markdown — фронт дергает этот эндпоинт."""
    return {"markdown": card_to_markdown(card)}