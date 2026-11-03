import asyncio
import json
import logging
import re
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.prompts import GENERATE_PROMPT, CRITIC_PROMPT
from app.schemas import LLMCard


logger = logging.getLogger(__name__)


class LLMEmptyResponseError(RuntimeError):
    """LLM вернула пустой content (reasoning съел весь max_tokens или провайдер вернул '')."""


class DraftState(TypedDict):
    raw_input: dict
    missing_fields: list[str]
    draft: Optional[dict]
    validation_errors: list[str]
    validation_iteration: int
    human_approved: bool
    feedback: Optional[str]
    critic_issues: list[str]
    critic_iteration: int
    iteration: int


class CritiqueResult(BaseModel):
    approved: bool = Field(description="true, если черновик готов к публикации без правок")
    issues: list[str] = Field(default_factory=list, description="Конкретные проблемы")


EXPECTED_SPEC_FIELDS = [
    "диапазон измерений", "класс точности", "присоединение",
    "выходной сигнал", "питание", "рабочая температура",
    "степень защиты", "интерфейсы", "материал корпуса",
    "диаметр корпуса", "габариты", "масса",
]

MAX_VALIDATION_RETRIES = 1
MIN_SEO_LEN_DEFAULT = 800
MIN_SEO_LEN_SPARSE = 400
MAX_SEO_LEN = 1200
SPARSE_THRESHOLD = 8

LLM_CALL_TIMEOUT_SECONDS = (
    settings.llm_timeout_seconds * (settings.llm_max_retries + 1) + 30
)


def _extract_numbers(text: str) -> set[str]:
    s = str(text).replace(",", ".")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    return {n for n in nums if len(n.replace(".", "")) >= 2}


_openai_client: Optional[AsyncOpenAI] = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    return _openai_client


async def _chat(prompt: str) -> str:
    """Прямой вызов LLM с диагностикой пустых ответов и reasoning-моделей."""
    client = _get_openai_client()
    kwargs = dict(
        model=settings.model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=settings.temperature,
    )
    if settings.max_tokens:
        kwargs["max_tokens"] = settings.max_tokens
    if settings.use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=LLM_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "LLM call exceeded hard timeout %.1fs (client timeout=%s, retries=%s)",
            LLM_CALL_TIMEOUT_SECONDS,
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
        )
        raise TimeoutError(
            f"LLM не ответила за {LLM_CALL_TIMEOUT_SECONDS:.0f} с"
        ) from exc

    choice = response.choices[0]
    msg = choice.message
    content = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""

    logger.info(
        "LLM response: model=%s finish_reason=%s usage=%s "
        "content_len=%d reasoning_len=%d content_preview=%r",
        response.model,
        choice.finish_reason,
        response.usage,
        len(content),
        len(reasoning),
        content[:200],
    )

    if not content.strip():
        if choice.finish_reason == "length" and reasoning.strip():
            raise LLMEmptyResponseError(
                f"Reasoning-модель '{settings.model_name}' исчерпала max_tokens "
                f"на размышлениях (max_tokens={settings.max_tokens}, "
                f"reasoning_len={len(reasoning)} символов). "
                "Поднимите MAX_TOKENS в backend/.env (например, до 32000) "
                "и перезапустите uvicorn."
            )
        raise LLMEmptyResponseError(
            f"LLM вернула пустой content "
            f"(finish_reason={choice.finish_reason}, usage={response.usage}). "
            f"MODEL_NAME='{settings.model_name}', "
            f"OPENAI_BASE_URL='{settings.openai_base_url}'."
        )

    return content


def _extract_json(text: str) -> dict:
    text = text.strip()

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise json.JSONDecodeError(
                "JSON-объект не найден в ответе LLM", text, 0
            )
        candidate = text[start:end + 1]

    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    return json.loads(candidate)


async def _invoke_structured(prompt: str, schema_cls):
    """Запрос к LLM + парсинг JSON в Pydantic-модель с одним retry.

    Первый вызов — исходный prompt как есть (в промптах уже сказано
    «Отвечай только JSON», так что hint не нужен). Если парсинг упал —
    второй вызов с усиленным hint'ом: перечисляем ожидаемые ключи,
    запрещаем markdown-обёртку и trailing comma.

    Один retry закрывает подавляющее большинство «сломанных» ответов
    (модель добавила ```json обёртку, оборвала строку, оставила
    trailing comma). Второй вызов дешевле, чем показать пользователю
    generic «Внутренняя ошибка сервера».
    """
    fields = ", ".join(schema_cls.model_fields.keys())

    content = await _chat(prompt)
    try:
        data = _extract_json(content)
        return schema_cls(**data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "JSON parse failed (%s: %s). Retry с усиленным hint. Ответ: %r",
            type(exc).__name__,
            exc,
            content[:500],
        )

    retry_prompt = (
        prompt
        + "\n\nВАЖНО: верни строго ОДИН JSON-объект без markdown-обёртки "
        + f"(без ```), без пояснений, с ключами: {fields}. "
        + "Строки экранируй корректно, никаких trailing comma."
    )
    content = await _chat(retry_prompt)

    try:
        data = _extract_json(content)
        return schema_cls(**data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error(
            "JSON parse failed и после retry (%s: %s). Ответ: %r",
            type(exc).__name__,
            exc,
            content[:800],
        )
        raise


def prepare_input(state: DraftState) -> dict:
    raw = state["raw_input"]
    specs = raw.get("specs") or {}
    present = {k.lower().strip() for k in specs}

    missing = [f for f in EXPECTED_SPEC_FIELDS if f not in present]
    if not raw.get("description") or len(raw["description"].strip()) < 30:
        missing.append("описание из паспорта")
    if not specs:
        missing.append("все характеристики")

    return {"missing_fields": missing}


async def generate_draft(state: DraftState) -> dict:
    raw = state["raw_input"]
    prompt = GENERATE_PROMPT.format(
        name=raw["name"],
        manufacturer=raw["manufacturer"],
        specs=raw.get("specs") or "не указаны",
        description=raw.get("description") or "не указано",
        missing_fields=", ".join(state.get("missing_fields", [])) or "нет",
    )

    if state.get("validation_errors"):
        prompt += (
            "\n\nИСПРАВЬ ОШИБКИ ПРЕДЫДУЩЕЙ ВЕРСИИ:\n"
            + "\n".join(f"- {e}" for e in state["validation_errors"])
        )
    if state.get("feedback"):
        prompt += f"\n\nЗАМЕЧАНИЯ РЕДАКТОРА:\n{state['feedback']}"
    if state.get("critic_issues"):
        prompt += "\n\nЗАМЕЧАНИЯ КРИТИКА:\n" + "\n".join(
            f"- {i}" for i in state["critic_issues"]
        )

    result: LLMCard = await _invoke_structured(prompt, LLMCard)
    draft = result.model_dump()

    specs_out: dict[str, str] = {}
    for k, v in (raw.get("specs") or {}).items():
        key = k.lower().strip() if isinstance(k, str) else str(k)
        specs_out[key] = v

    for field in EXPECTED_SPEC_FIELDS:
        if field not in specs_out:
            specs_out[field] = "данных нет"

    draft["specifications"] = specs_out

    return {
        "draft": draft,
        "validation_errors": [],
        "feedback": None,
        "critic_issues": [],
    }


def validate_draft(state: DraftState) -> dict:
    errors: list[str] = []
    draft = state.get("draft") or {}
    raw = state["raw_input"]
    missing = state.get("missing_fields", [])

    title = draft.get("title") or ""
    if not title:
        errors.append("Не заполнен title")
    elif len(title) > 70:
        errors.append(f"title: {len(title)} символов, нужно ≤ 70")

    sd = draft.get("short_description") or ""
    if not sd:
        errors.append("Не заполнен short_description")
    elif len(sd) > 200:
        errors.append(f"short_description: {len(sd)} символов, нужно ≤ 200")

    cb = draft.get("commercial_block") or ""
    if not cb.strip():
        errors.append("Не заполнен commercial_block")
    elif not (200 <= len(cb) <= 400):
        errors.append(f"commercial_block: {len(cb)} символов, нужно 200–400")

    seo = draft.get("seo_description") or ""
    seo_len = len(seo)
    min_len = MIN_SEO_LEN_SPARSE if len(missing) >= SPARSE_THRESHOLD else MIN_SEO_LEN_DEFAULT
    if seo_len < min_len or seo_len > MAX_SEO_LEN:
        errors.append(
            f"seo_description: {seo_len} символов, нужно {min_len}–{MAX_SEO_LEN}"
        )

    if not 3 <= len(draft.get("key_features") or []) <= 5:
        errors.append(f"key_features: {len(draft.get('key_features') or [])}, нужно 3–5")
    if not 3 <= len(draft.get("search_queries") or []) <= 5:
        errors.append(f"search_queries: {len(draft.get('search_queries') or [])}, нужно 3–5")

    allowed: set[str] = set()
    for src in [raw.get("name", ""), raw.get("description", "")] + list((raw.get("specs") or {}).values()):
        allowed |= _extract_numbers(str(src))

    text = " ".join([
        draft.get("title", ""),
        draft.get("short_description", ""),
        draft.get("seo_description", ""),
        draft.get("commercial_block", ""),
        " ".join(draft.get("key_features") or []),
        " ".join(draft.get("applications") or []),
        " ".join(draft.get("search_queries") or []),
    ])
    invented = _extract_numbers(text) - allowed
    if invented:
        errors.append(f"Выдуманные числа: {sorted(invented)}")

    new_iter = state.get("validation_iteration", 0) + (1 if errors else 0)
    return {"validation_errors": errors, "validation_iteration": new_iter}


async def critic(state: DraftState) -> dict:
    if state.get("critic_iteration", 0) >= 1:
        return {"critic_issues": []}

    result: CritiqueResult = await _invoke_structured(
        CRITIC_PROMPT.format(
            raw_specs=state["raw_input"].get("specs") or {},
            draft=state["draft"],
        ),
        CritiqueResult,
    )
    if result.approved:
        return {"critic_issues": []}
    return {
        "critic_issues": result.issues,
        "critic_iteration": state.get("critic_iteration", 0) + 1,
    }


async def human_review(state: DraftState) -> dict:
    decision = interrupt({
        "draft": state["draft"],
        "validation_errors": state.get("validation_errors", []),
        "missing_fields": state.get("missing_fields", []),
        "iteration": state.get("iteration", 0),
        "message": "Проверьте черновик: одобрить или отправить на доработку",
    })
    return {
        "human_approved": decision.get("approved", False),
        "draft": decision.get("edited_draft") or state["draft"],
        "feedback": decision.get("feedback"),
        "iteration": state.get("iteration", 0) + 1,
        "critic_iteration": 0,
        "validation_iteration": 0,
    }


def route_after_validate(state: DraftState) -> str:
    if state.get("validation_errors") and state.get("validation_iteration", 0) < MAX_VALIDATION_RETRIES:
        return "regenerate"
    return "critic" if settings.use_critic else "review"


def route_after_critic(state: DraftState) -> str:
    return "regenerate" if state.get("critic_issues") else "review"


def route_after_review(state: DraftState) -> str:
    if state.get("human_approved"):
        return "end"
    if state.get("iteration", 0) >= 3:
        return "end"
    return "regenerate"


def build_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(DraftState)
    builder.add_node("prepare_input", prepare_input)
    builder.add_node("generate_draft", generate_draft)
    builder.add_node("validate_draft", validate_draft)
    builder.add_node("critic", critic)
    builder.add_node("human_review", human_review)

    builder.set_entry_point("prepare_input")
    builder.add_edge("prepare_input", "generate_draft")
    builder.add_edge("generate_draft", "validate_draft")
    builder.add_conditional_edges(
        "validate_draft", route_after_validate,
        {
            "regenerate": "generate_draft",
            "critic": "critic",
            "review": "human_review",
        },
    )
    builder.add_conditional_edges(
        "critic", route_after_critic,
        {"regenerate": "generate_draft", "review": "human_review"},
    )
    builder.add_conditional_edges(
        "human_review", route_after_review,
        {"regenerate": "generate_draft", "end": END},
    )
    return builder.compile(checkpointer=checkpointer)

_async_graph = None
_async_graph_lock: Optional[asyncio.Lock] = None


async def get_async_graph():
    """Возвращает единственный граф с MemorySaver (синглтон на процесс)."""
    global _async_graph, _async_graph_lock
    if _async_graph is not None:
        return _async_graph
    if _async_graph_lock is None:
        _async_graph_lock = asyncio.Lock()
    async with _async_graph_lock:
        if _async_graph is None:
            if settings.checkpoint_db != ":memory:":
                logger.warning(
                    "CHECKPOINT_DB=%r проигнорирован — используется MemorySaver "
                    "(in-RAM). Состояние теряется при restart/reload. "
                    "Для сохранения между перезапусками верните AsyncSqliteSaver.",
                    settings.checkpoint_db,
                )
            _async_graph = build_graph(MemorySaver())
        return _async_graph


async def shutdown_async_graph() -> None:
    """Закрывает OpenAI-клиент. MemorySaver закрывать не нужно."""
    global _async_graph, _openai_client
    _async_graph = None
    if _openai_client is not None:
        try:
            await _openai_client.close()
            logger.info("OpenAI-клиент закрыт")
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка при закрытии openai-клиента")
        _openai_client = None


graph = build_graph()