from __future__ import annotations

import asyncio

import pytest

from app.workers.async_runner import run_worker_coroutine


async def _return_value(value: int) -> int:
    await asyncio.sleep(0)
    return value


async def _current_loop_class_name() -> str:
    return type(asyncio.get_running_loop()).__name__


def test_run_worker_coroutine_returns_result() -> None:
    assert run_worker_coroutine(_return_value(7)) == 7


def test_run_worker_coroutine_propagates_exceptions() -> None:
    async def _raise() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_worker_coroutine(_raise())


def test_run_worker_coroutine_uses_selector_loop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.workers.async_runner.sys.platform", "win32")

    loop_name = run_worker_coroutine(_current_loop_class_name())

    assert "Proactor" not in loop_name
    assert "SelectorEventLoop" in loop_name


def test_run_worker_coroutine_uses_asyncio_run_on_other_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.workers.async_runner.sys.platform", "linux")
    calls: list[object] = []
    real_run = asyncio.run

    def _tracking_run(coro: object, *args: object, **kwargs: object) -> object:
        calls.append(coro)
        return real_run(coro, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.workers.async_runner.asyncio.run", _tracking_run)

    assert run_worker_coroutine(_return_value(3)) == 3
    assert len(calls) == 1
