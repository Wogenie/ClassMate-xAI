"""Cross-thread coroutine scheduling.

FastAPI sync endpoints run in a threadpool, while the Telegram bot lives on the
main asyncio loop. This lets sync code safely hand coroutines to the loop that
started at app lifespan.
"""
import asyncio
import logging

log = logging.getLogger("classmate.looputil")

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def call_coro(coro) -> None:
    """Schedule a coroutine onto the main loop (safe from any thread)."""
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        try:
            _main_loop = asyncio.get_event_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
    if _main_loop.is_closed():
        asyncio.run(coro)
        return
    _main_loop.call_soon_threadsafe(lambda: _main_loop.create_task(coro))


def run_coro(coro, timeout: float = 30.0):
    """Run a coroutine ON the main loop thread and wait for its result.

    Safe from any thread; returns the coroutine's return value. Used instead of
    `call_coro` when the caller needs an immediate answer (e.g. an agent tool
    that posts a poll and must report whether it succeeded).
    """
    global _main_loop
    loop = _main_loop
    if loop is None or loop.is_closed():
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return asyncio.run(coro)
    if loop.is_closed():
        return asyncio.run(coro)
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout)