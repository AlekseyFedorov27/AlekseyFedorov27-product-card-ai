from pydantic import BaseModel, Field, field_validator


class ProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str = Field(min_length=1, max_length=200)
    specs: dict[str, str] = Field(default_factory=dict)
    description: str = Field(default="", max_length=5000)

    @field_validator("name", "manufacturer")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("поле не может быть пустым")
        return v.strip()

    @field_validator("description")
    @classmethod
    def desc_trim(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("specs", mode="before")
    @classmethod
    def specs_clean(cls, v):
        """Приведение specs к dict[str, str].

        Числа/float приводятся к строке, bool → «да»/«нет», None → ''.
        Значения-контейнеры (dict/list/tuple) отклоняются — это почти всегда
        ошибка ввода, а не данные прибора.
        """
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("specs должен быть объектом {параметр: значение}")
        cleaned: dict[str, str] = {}
        for k, val in v.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("названия характеристик должны быть непустыми строками")
            if isinstance(val, bool):
                val = "да" if val else "нет"
            elif isinstance(val, (int, float)):
                val = str(val)
            elif val is None:
                val = ""
            elif isinstance(val, str):
                val = val.strip()
            else:
                raise ValueError(
                    f"значение «{k.strip()}» должно быть строкой или числом "
                    f"(получено {type(val).__name__})"
                )
            cleaned[k.strip()] = val
        return cleaned


class LLMCard(BaseModel):
    """Что возвращает LLM. Specifications намеренно отсутствует —
    таблица собирается из входа кодом, чтобы исключить потери/выдумки."""
    title: str = Field(description="SEO-заголовок, до 70 символов, модель + назначение")
    short_description: str = Field(description="1–2 предложения для листинга, до 200 символов")
    seo_description: str = Field(description="SEO-описание 800–1200 символов")
    commercial_block: str = Field(description="Для менеджера: кому и какие задачи, 200–400 символов")
    key_features: list[str] = Field(description="3–5 пунктов, каждая до 100 символов")
    applications: list[str] = Field(description="3–5 типовых областей применения")
    search_queries: list[str] = Field(description="3–5 поисковых фраз на русском")


class ProductCard(BaseModel):
    """Финальный ответ. specifications — точная копия входных specs."""
    title: str
    short_description: str
    seo_description: str
    commercial_block: str
    key_features: list[str]
    specifications: dict[str, str]
    applications: list[str]
    search_queries: list[str]


class ApproveRequest(BaseModel):
    approved: bool
    edited_draft: ProductCard | None = None
    feedback: str | None = None