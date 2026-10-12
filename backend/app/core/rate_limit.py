"""Limite simples (em memória) de tentativas de login. Em produção, usar Redis."""
import time
from collections import defaultdict, deque

MAX_ATTEMPTS = 8
WINDOW_SECONDS = 60
_attempts: dict[str, deque] = defaultdict(deque)


def _prune(key: str) -> deque:
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return q


def is_blocked(key: str) -> bool:
    return len(_prune(key)) >= MAX_ATTEMPTS


def register_failure(key: str) -> None:
    _prune(key).append(time.monotonic())


def reset() -> None:
    _attempts.clear()
