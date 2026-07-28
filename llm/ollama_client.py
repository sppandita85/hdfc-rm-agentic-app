"""ChatOllama factory. Kept in one place so the timeout policy is applied consistently."""
from __future__ import annotations

from langchain_ollama import ChatOllama

from config.settings import settings

_llm: ChatOllama | None = None


def get_llm() -> ChatOllama:
    """Returns a process-wide ChatOllama instance with a hard request timeout.

    A timeout is required here: without one, a wedged Ollama model slot could hang a graph
    run indefinitely with an RM waiting on the other end. Callers must still wrap
    invocations in try/except and fall back to their deterministic path on failure — every
    LLM node in this project has one, so a dead Ollama degrades the app rather than
    breaking it.
    """
    global _llm
    if _llm is None:
        _llm = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_host,
            temperature=0.2,
            client_kwargs={"timeout": settings.ollama_timeout_s},
        )
    return _llm


def reset_llm() -> None:
    """Drops the cached client. Only used by the smoke test, which flips OLLAMA_HOST to a
    dead port mid-run to prove the degraded-mode fallbacks work."""
    global _llm
    _llm = None


def ollama_available() -> tuple[bool, str]:
    """Cheap reachability probe for the UI's status banner. Never raises."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{settings.ollama_host}/api/tags", timeout=3):
            return True, ""
    except Exception as exc:  # noqa: BLE001 - any failure means "show the banner"
        return False, str(exc)
