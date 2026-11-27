"""Authentication types for the SEMS API adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

type TokenType = Literal["legacy", "new", "web"]
type LoginHandler = Callable[[str, str], dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class TokenProfile:
    """Login and invalidation behavior for one token type."""

    login: LoginHandler
    invalidates: tuple[TokenType, ...] = ()
