"""Сценарные тесты графа: валидация входа, happy path, human-in-the-loop.

Запуск из backend/:
    python scripts/run_tests.py

Флаги:
    --no-color      отключить ANSI-цвета
    --only=A,B,C    прогнать только указанные категории
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
import uuid
import warnings
from pathlib import Path

# langgraph импортируется ДО app.*, поэтому фильтр нужен здесь, до
# всех остальных импортов. См. также app/__init__.py (покрывает uvicorn).
warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change",
)

from pydantic import ValidationError  # noqa: E402

# чтобы `import app.*` работал при запуске из backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command  # noqa: E402

from app.graph import graph  # noqa: E402
from app.schemas import ProductInput  # noqa: E402


# ────────────────────────────────────────────────────────────────
# Цветной вывод
# ────────────────────────────────────────────────────────────────

USE_COLOR = True


def c(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(msg: str) -> str:
    return c("✅ " + msg, "32")


def fail(msg: str) -> str:
    return c("❌ " + msg, "31")


def head(msg: str) -> str:
    return c(msg, "1;36")


# ────────────────────────────────────────────────────────────────
# Тестовые данные
# ────────────────────────────────────────────────────────────────

# Категория A: неполные / некорректные входные данные.
# (описание, dict, ожидаемое_поле_ошибки)
BAD_INPUT_CASES = [
    (
        "Пустое name",
        {"name": "", "manufacturer": "X", "specs": {"a": "b"}, "description": "x" * 40},
        "name",
    ),
    (
        "Пустой manufacturer",
        {"name": "Y", "manufacturer": "   ", "specs": {"a": "b"}, "description": "x" * 40},
        "manufacturer",
    ),
    (
        "specs не является объектом",
        {"name": "Y", "manufacturer": "X", "specs": "not-a-dict", "description": "x" * 40},
        "specs",
    ),
    (
        "Пустой ключ в specs",
        {"name": "Y", "manufacturer": "X", "specs": {"   ": "v"}, "description": "x" * 40},
        "specs",
    ),
]

# Позитивные кейсы коэрсии: числовые/bool/None значения specs
# приводятся к строке, а не падают с ValidationError.
# (описание, raw_specs, ожидаемый_dict)
SPECS_COERCION_CASES = [
    ("int → str", {"a": 123}, {"a": "123"}),
    ("float → str", {"класс точности": 1.5}, {"класс точности": "1.5"}),
    ("bool → да/нет", {"b": True, "c": False}, {"b": "да", "c": "нет"}),
    ("None → пусто", {"n": None}, {"n": ""}),
]

# Категория B: полноценные входы, граф должен дойти до human_review.
GOOD_CASES = [
    {
        "name": "Манометр показывающий DM 02",
        "manufacturer": "Манотомь",
        "specs": {
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
            "присоединение": "G1/2",
            "диаметр корпуса": "100 мм",
            "рабочая температура": "−50…+60 °C",
            "степень защиты": "IP54",
        },
        "description": (
            "Прибор предназначен для измерения избыточного давления неагрессивных "
            "к медным сплавам жидкостей и газов. Применяется в системах отопления, "
            "водоснабжения и технологических трубопроводах. Корпус из нержавеющей "
            "стали, ударопрочное стекло, встроенный демпфер для защиты от вибрации."
        ),
    },
    {
        "name": "Датчик давления ДД 100",
        "manufacturer": "Элемер",
        "specs": {
            "диапазон измерений": "0–10 МПа",
            "класс точности": "0,25",
            "выходной сигнал": "4–20 мА",
            "питание": "24 В DC",
            "присоединение": "M20×1,5",
            "степень защиты": "IP65",
            "рабочая температура": "−40…+85 °C",
        },
        "description": (
            "Датчик предназначен для непрерывного преобразования избыточного "
            "давления в унифицированный токовый сигнал 4–20 мА. Применяется в "
            "системах автоматического контроля и регулирования технологических "
            "процессов. Корпус из нержавеющей стали."
        ),
    },
    {
        "name": "Термопара ТХА-0192",
        "manufacturer": "Элемер",
        "specs": {
            "тип": "ХА (хромель-алюмель)",
            "диапазон измерений": "0…+1100 °C",
            "класс точности": "2",
            "диаметр гильзы": "6 мм",
            "длина монтажной части": "320 мм",
            "степень защиты": "IP65",
        },
        "description": (
            "Термопара предназначена для измерения температуры в промышленных "
            "печах, котельных установках и технологических трубопроводах. "
            "Хромель-алюмелевый спай обеспечивает работу в окислительных средах."
        ),
    },
    {
        "name": "Преобразователь давления Метран-150",
        "manufacturer": "Метран",
        "specs": {
            "диапазон измерений": "0–2,5 МПа",
            "класс точности": "0,5",
            "выходной сигнал": "4–20 мА / HART",
            "питание": "24 В DC",
            "присоединение": "1/2 NPT",
            "степень защиты": "IP66",
        },
        "description": (
            "Преобразователь предназначен для измерения и передачи избыточного "
            "давления в системах автоматизации. Поддерживает протокол HART, "
            "конфигурируется дистанционно. Применяется в нефтяной, газовой и "
            "химической промышленности."
        ),
    },
]

# Категория C: сценарии human-in-the-loop.
# Каждый кейс — список решений, которые «пользователь» отправляет через resume.
# {approved: bool, feedback: str|None}
ITERATION_CASES = [
    (
        "1 отказ → перегенерация → одобрение",
        [
            {"approved": False, "feedback": "Добавь упоминание взрывозащиты, если применимо"},
            {"approved": True, "feedback": None},
        ],
        True,
    ),
    (
        "2 отказа → 2 перегенерации → одобрение",
        [
            {"approved": False, "feedback": "Убери маркетинговые фразы, добавь конкретики"},
            {"approved": False, "feedback": "Сократи full_description до 1200 символов"},
            {"approved": True, "feedback": None},
        ],
        True,
    ),
    (
        "3 отказа подряд → достигнут лимит итераций",
        [
            {"approved": False, "feedback": "Перепиши в другом стиле"},
            {"approved": False, "feedback": "Перепиши в другом стиле"},
            {"approved": False, "feedback": "Перепиши в другом стиле"},
        ],
        False,
    ),
    (
        "Отказ без feedback → перегенерация всё равно происходит",
        [
            {"approved": False, "feedback": None},
            {"approved": True, "feedback": None},
        ],
        True,
    ),
]


# ────────────────────────────────────────────────────────────────
# Проверки
# ────────────────────────────────────────────────────────────────

def run_category_a() -> tuple[int, int]:
    """A. Валидация входа: ProductInput должен либо бросить ValidationError
    (некорректный тип specs/пустые строки), либо привести числа к строке."""
    head("\n[A] Валидация входных данных")

    passed = total = 0

    # Негативные кейсы: ожидаем ValidationError по конкретному полю.
    for desc, payload, expected_field in BAD_INPUT_CASES:
        total += 1
        try:
            ProductInput(**payload)
        except ValidationError as e:
            errors_text = str(e).lower()
            if expected_field.lower() in errors_text:
                passed += 1
                print("  " + ok(f"{desc} → ValidationError по полю «{expected_field}»"))
            else:
                print("  " + fail(
                    f"{desc} → ValidationError, но не по полю «{expected_field}»:\n"
                    f"     {errors_text[:300]}"
                ))
        except Exception as e:  # noqa: BLE001
            print("  " + fail(f"{desc} → неожиданное исключение: {e}"))
        else:
            print("  " + fail(f"{desc} → ProductInput принял некорректные данные"))

    # Позитивные кейсы: коэрсия значений specs в строку.
    for desc, raw_specs, expected in SPECS_COERCION_CASES:
        total += 1
        try:
            card = ProductInput(
                name="Y",
                manufacturer="X",
                specs=raw_specs,
                description="x" * 40,
            )
        except Exception as e:  # noqa: BLE001
            print("  " + fail(f"{desc} → неожиданное исключение: {e}"))
            continue
        if card.specs == expected:
            passed += 1
            print("  " + ok(f"{desc} → specs приведены корректно"))
        else:
            print("  " + fail(
                f"{desc} → specs={card.specs!r}, ожидалось {expected!r}"
            ))

    return passed, total


def _assert_draft_quality(state_values: dict) -> list[str]:
    problems: list[str] = []
    draft = state_values.get("draft") or {}

    if not draft.get("title") or len(draft["title"]) > 70:
        problems.append("title пуст или > 70")
    seo_len = len(draft.get("seo_description") or "")
    min_len = 400 if len(state_values.get("missing_fields") or []) >= 3 else 800
    if not min_len <= seo_len <= 1200:
        problems.append(f"seo_description {seo_len}, нужно {min_len}–1200")
    if not 3 <= len(draft.get("key_features") or []) <= 5:
        problems.append("key_features не 3–5")
    if not 3 <= len(draft.get("search_queries") or []) <= 5:
        problems.append("search_queries не 3–5")
    if not draft.get("commercial_block"):
        problems.append("нет commercial_block")
    if not draft.get("specifications"):
        problems.append("specifications пусто")
    if state_values.get("validation_errors"):
        problems.append(f"validation_errors: {state_values['validation_errors']}")
    return problems


async def run_category_b() -> tuple[int, int]:
    """B. Happy path: граф доходит до human_review без ошибок."""
    head("\n[B] Полный happy path до human_review")
    passed = total = 0
    for case in GOOD_CASES:
        total += 1
        name = case["name"]
        thread_id = f"test-b-{uuid.uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await graph.ainvoke({"raw_input": case}, config=config)
            snapshot = await graph.aget_state(config)

            if "human_review" not in snapshot.next:
                print("  " + fail(
                    f"{name} → не остановился на human_review, next={snapshot.next}"
                ))
                continue

            problems = _assert_draft_quality(snapshot.values)
            if problems:
                print("  " + fail(f"{name} → {'; '.join(problems)}"))
                continue

            await graph.ainvoke(
                Command(resume={"approved": True, "edited_draft": None, "feedback": None}),
                config=config,
            )
            passed += 1
            print("  " + ok(f"{name} → human_review, черновик валиден"))
        except Exception as e:  # noqa: BLE001
            print("  " + fail(f"{name} → исключение: {e}"))
            traceback.print_exc()
    return passed, total


async def run_category_c() -> tuple[int, int]:
    """C. Итерации: серия решений через resume, проверка перегенерации и лимита."""
    head("\n[C] Human-in-the-loop с итерациями")
    passed = total = 0
    base_case = GOOD_CASES[0]

    for desc, decisions, expect_approved in ITERATION_CASES:
        total += 1
        thread_id = f"test-c-{uuid.uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await graph.ainvoke({"raw_input": base_case}, config=config)
            snap = await graph.aget_state(config)
            if "human_review" not in snap.next:
                print("  " + fail(f"{desc} → граф не остановился на human_review"))
                continue

            regenerated_count = 0
            for decision in decisions:
                await graph.ainvoke(
                    Command(resume={
                        "approved": decision["approved"],
                        "edited_draft": None,
                        "feedback": decision["feedback"],
                    }),
                    config=config,
                )
                snap = await graph.aget_state(config)

                if decision["approved"]:
                    if snap.next:
                        print("  " + fail(
                            f"{desc} → после approve граф не завершён, next={snap.next}"
                        ))
                        break
                else:
                    if "human_review" in snap.next:
                        regenerated_count += 1
                    elif not snap.next:
                        pass
                    else:
                        print("  " + fail(
                            f"{desc} → после отказа неожиданное состояние, next={snap.next}"
                        ))
                        break
            else:
                final_approved = snap.values.get("human_approved", False)
                if final_approved != expect_approved:
                    print("  " + fail(
                        f"{desc} → human_approved={final_approved}, ожидалось {expect_approved}"
                    ))
                    continue
                if expect_approved and regenerated_count == 0:
                    print("  " + fail(f"{desc} → перегенерация не произошла"))
                    continue
                if not expect_approved and snap.next:
                    print("  " + fail(f"{desc} → граф не завершился после лимита"))
                    continue
                passed += 1
                print("  " + ok(
                    f"{desc} → перегенераций: {regenerated_count}, "
                    f"approved={final_approved}"
                ))
        except Exception as e:  # noqa: BLE001
            print("  " + fail(f"{desc} → исключение: {e}"))
            traceback.print_exc()
    return passed, total


# ────────────────────────────────────────────────────────────────
# Запуск
# ────────────────────────────────────────────────────────────────

async def main() -> int:
    global USE_COLOR
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--only", default="A,B,C", help="A,B,C — через запятую")
    args = parser.parse_args()

    USE_COLOR = not args.no_color
    only = {s.strip().upper() for s in args.only.split(",")}

    print(head("\n════════════════════════════════════════════════════════════"))
    print(head("  AI-помощник карточек товаров — сценарные тесты"))
    print(head("════════════════════════════════════════════════════════════"))

    results: dict[str, tuple[int, int]] = {}
    if "A" in only:
        results["A"] = run_category_a()
    if "B" in only:
        results["B"] = await run_category_b()
    if "C" in only:
        results["C"] = await run_category_c()

    print(head("\n════════════════════════════════════════════════════════════"))
    total_passed = sum(p for p, _ in results.values())
    total_cases = sum(t for _, t in results.values())
    for label, (p, t) in results.items():
        color = "32" if p == t else "31"
        print(f"  {c(f'[{label}]', '1')} {c(f'{p}/{t}', color)}")
    print(head("────────────────────────────────────────────────────────────"))
    color = "32" if total_passed == total_cases else "31"
    print(f"  {c(f'ИТОГО: {total_passed}/{total_cases}', '1;' + color)}")
    print(head("════════════════════════════════════════════════════════════\n"))

    return 0 if total_passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))