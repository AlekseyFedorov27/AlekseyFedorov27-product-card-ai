"""Диагностика LLM-эндпоинта.

Запуск из backend/:
    python scripts/diag_llm.py

Показывает:
  - настройки (masked api_key);
  - список моделей, доступных у провайдера, с пометкой reasoning;
  - ответы на 5 вариантов параметров: finish_reason / usage / content_len / reasoning_len.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.prompts import GENERATE_PROMPT  # noqa: E402


TEST_INPUT = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
    "description": "Прибор для измерения избыточного давления.",
    "missing_fields": "нет",
}

JSON_SUFFIX = (
    "\n\nВерни ТОЛЬКО валидный JSON без markdown-обёртки и пояснений. "
    "Ключи: title, short_description, seo_description, commercial_block, "
    "key_features, applications, search_queries."
)

REASONING_MARKERS = ("-reasoner", "-r1", "-thinking", "o1", "o3", "qwq", "-flash")


def _mask(key: str) -> str:
    if not key:
        return "(пусто!)"
    return f"{'*' * 8}{key[-4:]}"


def _looks_like_reasoning(model_id: str) -> bool:
    mid = model_id.lower()
    return any(m in mid for m in REASONING_MARKERS)


async def _list_models(client: AsyncOpenAI) -> list[str]:
    try:
        resp = await client.models.list()
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ /models недоступен: {type(exc).__name__}: {exc}")
        return []
    ids = [m.id for m in resp.data]
    print(f"  Всего моделей: {len(ids)}")
    non_reasoning = [i for i in ids if not _looks_like_reasoning(i)]
    reasoning = [i for i in ids if _looks_like_reasoning(i)]

    print("  ✅ Не-reasoning (рекомендуется):")
    for i in non_reasoning[:40]:
        print(f"     - {i}")
    if len(non_reasoning) > 40:
        print(f"     ... и ещё {len(non_reasoning) - 40}")

    if reasoning:
        print("  ⚠️  Reasoning (НЕ использовать для JSON-генерации):")
        for i in reasoning[:10]:
            print(f"     - {i}")
    return ids


async def main() -> int:
    print("=== Настройки (из .env / env) ===")
    print(f"  OPENAI_BASE_URL     = {settings.openai_base_url}")
    print(f"  MODEL_NAME          = {settings.model_name}")
    print(f"  OPENAI_API_KEY      = {_mask(settings.openai_api_key)}")
    print(f"  TEMPERATURE         = {settings.temperature}")
    print(f"  MAX_TOKENS          = {settings.max_tokens}")
    print(f"  USE_JSON_MODE       = {settings.use_json_mode}")
    print(f"  LLM_TIMEOUT_SECONDS = {settings.llm_timeout_seconds}")
    print(f"  LLM_MAX_RETRIES     = {settings.llm_max_retries}")

    if not settings.openai_api_key:
        print("\n❌ OPENAI_API_KEY пустой — заполните .env")
        return 1

    if _looks_like_reasoning(settings.model_name):
        print(
            f"\n⚠️  MODEL_NAME='{settings.model_name}' выглядит как reasoning-модель. "
            "Она будет тратить max_tokens на reasoning_content, а не на JSON."
        )

    # Клиент диагностики: retries=0, таймаут 180 с — не хотим ждать по 4 минуты.
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=180.0,
        max_retries=0,
    )

    print("\n=== Доступные модели ===")
    await _list_models(client)

    prompt = GENERATE_PROMPT.format(**TEST_INPUT) + JSON_SUFFIX

    variants = [
        ("max_tokens=4000, temp=0.3", {"max_tokens": 4000, "temperature": 0.3}),
        ("max_tokens=8000, temp=0.3", {"max_tokens": 8000, "temperature": 0.3}),
        ("max_tokens=16000, temp=0.3", {"max_tokens": 16000, "temperature": 0.3}),
        ("только temperature", {"temperature": 0.3}),
        ("без доп. параметров", {}),
    ]

    any_ok = False
    working_variant: str | None = None

    for label, extra in variants:
        print(f"\n=== Вариант: {label} ===")
        try:
            resp = await client.chat.completions.create(
                model=settings.model_name,
                messages=[{"role": "user", "content": prompt}],
                **extra,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {type(exc).__name__}: {exc}")
            continue

        choice = resp.choices[0]
        msg = choice.message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""

        print(f"  model            : {resp.model}")
        print(f"  finish_reason    : {choice.finish_reason}")
        print(f"  usage            : {resp.usage}")
        print(f"  content_len      : {len(content)}")
        print(f"  content_preview  : {content[:200]!r}")
        if reasoning:
            print(f"  reasoning_len    : {len(reasoning)}")

        if content.strip():
            print("  ✅ content непустой")
            any_ok = True
            working_variant = working_variant or label
        elif reasoning.strip() and choice.finish_reason == "length":
            print("  ⚠️  reasoning-модель: весь max_tokens ушёл в размышления")
        elif reasoning.strip():
            print("  ⚠️  content пуст, но есть reasoning_content (finish_reason≠length)")
        else:
            print("  ❌ пустой ответ")

    await client.close()

    print("\n=== Итог ===")
    if any_ok:
        print(f"Работающий вариант: «{working_variant}»")
        print("Примените соответствующий MAX_TOKENS в .env и перезапустите uvicorn.")
        return 0

    print("Ни один вариант не вернул content. Скорее всего — reasoning-модель.")
    print("Решение: сменить MODEL_NAME на не-reasoning модель из списка выше,")
    print("например gpt-4o-mini (OpenAI) или deepseek-chat (DeepSeek).")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))