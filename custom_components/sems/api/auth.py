"""Authentication types for the SEMS API adapter."""

from collections.abc import Callable
from typing import Any, Literal

type TokenType = Literal["legacy", "new", "web"]
type LoginHandler = Callable[[str, str], dict[str, Any] | None]
