"""python cli.py fixtures/product_1.json [--reject "фидбек"]"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from langgraph.types import Command
from openai import APITimeoutError, AuthenticationError, RateLimitError
from pydantic import ValidationError

from app.api import card_to_markdown
from app.graph import graph
from app.schemas import ProductCard, ProductInput


async def _run(args) -> int:
    data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    input_data = ProductInput(**data)

    thread_id = f"cli-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke({"raw_input": input_data.model_dump()}, config=config)

    feedbacks = list(args.reject)
    for _ in range(args.max_loops):
        snap = await graph.aget_state(config)
        if not snap.next:
            break
        if "human_review" not in snap.next:
            continue
        fb = feedbacks.pop(0) if feedbacks else None
        await graph.ainvoke(
            Command(resume={"approved": fb is None, "edited_draft": None, "feedback": fb}),
            config=config,
        )

    final = await graph.aget_state(config)

    leftover = final.values.get("validation_errors") or []
    if leftover:
        print("⚠️  Остаточные замечания валидатора:", file=sys.stderr)
        for e in leftover:
            print(f"   - {e}", file=sys.stderr)

    if not final.values.get("human_approved") and final.next:
        print("⚠️  Граф не завершён (лимит итераций)", file=sys.stderr)

    draft = final.values.get("draft")
    if not draft:
        print("❌ Черновик не сгенерирован", file=sys.stderr)
        return 1

    missing = final.values.get("missing_fields") or []
    if missing:
        print(f"ℹ️  Отсутствующие данные: {', '.join(missing)}", file=sys.stderr)

    print(card_to_markdown(ProductCard(**draft)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация карточки товара из JSON")
    parser.add_argument("fixture")
    parser.add_argument("--reject", action="append", default=[])
    parser.add_argument("--max-loops", type=int, default=6)
    args = parser.parse_args()

    try:
        return asyncio.run(_run(args))
    except FileNotFoundError:
        print(f"❌ Файл не найден: {args.fixture}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"❌ Некорректный JSON в {args.fixture}: {e}", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"❌ Некорректные входные данные:\n{e}", file=sys.stderr)
        return 2
    except AuthenticationError:
        print("❌ Неверный API-ключ LLM", file=sys.stderr)
        return 3
    except RateLimitError:
        print("❌ Лимит запросов к LLM исчерпан", file=sys.stderr)
        return 3
    except APITimeoutError:
        print("❌ LLM не ответила вовремя", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())