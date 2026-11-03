"""Пакет приложения.

Здесь ставим фильтр до импорта app.graph: при старте uvicorn package
инициализируется первым, поэтому этот фильтр сработает раньше, чем
langgraph.checkpoint.serde.jsonplus бросит PendingDeprecationWarning.
"""

import warnings

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change",
)