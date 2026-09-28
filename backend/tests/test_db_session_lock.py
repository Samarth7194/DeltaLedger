from __future__ import annotations

import asyncio

import pytest

from app.db.session import held_advisory_lock


class _FakeCursorResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class _FakeConnection:
    def __init__(self, *, lock_acquired: bool) -> None:
        self.lock_acquired = lock_acquired
        self.executed: list[str] = []
        self.closed = False
        self.execution_options_calls: list[dict[str, object]] = []

    async def execution_options(self, **kwargs: object) -> _FakeConnection:
        self.execution_options_calls.append(kwargs)
        return self

    async def execute(self, clause: object) -> _FakeCursorResult:
        text_repr = str(clause)
        self.executed.append(text_repr)
        if "pg_try_advisory_lock" in text_repr:
            return _FakeCursorResult(self.lock_acquired)
        if "pg_advisory_unlock" in text_repr:
            return _FakeCursorResult(True)
        return _FakeCursorResult(None)


class _FakeConnectionContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *exc: object) -> bool:
        self._connection.closed = True
        return False


class _FakeEngine:
    def __init__(self, *, lock_acquired: bool) -> None:
        self.connection = _FakeConnection(lock_acquired=lock_acquired)

    def connect(self) -> _FakeConnectionContext:
        return _FakeConnectionContext(self.connection)


@pytest.mark.asyncio
async def test_held_advisory_lock_yields_false_and_closes_when_already_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = _FakeEngine(lock_acquired=False)
    monkeypatch.setattr("app.db.session.engine", fake_engine)

    async with held_advisory_lock(123) as acquired:
        assert acquired is False

    assert fake_engine.connection.closed is True
    # Never attempted to unlock a lock it never held.
    assert not any("pg_advisory_unlock" in call for call in fake_engine.connection.executed)


@pytest.mark.asyncio
async def test_held_advisory_lock_yields_true_and_releases_on_normal_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = _FakeEngine(lock_acquired=True)
    monkeypatch.setattr("app.db.session.engine", fake_engine)

    async with held_advisory_lock(123) as acquired:
        assert acquired is True

    assert any("pg_advisory_unlock" in call for call in fake_engine.connection.executed)
    assert fake_engine.connection.closed is True
    # Session-level advisory locks don't need transactional durability;
    # AUTOCOMMIT also avoids leaving this connection "idle in transaction"
    # for as long as the lock is held.
    assert fake_engine.connection.execution_options_calls == [{"isolation_level": "AUTOCOMMIT"}]


@pytest.mark.asyncio
async def test_held_advisory_lock_releases_even_if_the_caller_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = _FakeEngine(lock_acquired=True)
    monkeypatch.setattr("app.db.session.engine", fake_engine)

    with pytest.raises(ValueError, match="boom"):
        async with held_advisory_lock(123) as acquired:
            assert acquired is True
            raise ValueError("boom")

    assert any("pg_advisory_unlock" in call for call in fake_engine.connection.executed)
    assert fake_engine.connection.closed is True


@pytest.mark.asyncio
async def test_held_advisory_lock_cancels_its_keepalive_task_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keepalive task must not outlive the lock - a leaked background
    task would keep pinging a connection nothing needs anymore."""
    fake_engine = _FakeEngine(lock_acquired=True)
    monkeypatch.setattr("app.db.session.engine", fake_engine)
    monkeypatch.setattr("app.db.session._ADVISORY_LOCK_KEEPALIVE_INTERVAL_SECONDS", 0.01)

    async with held_advisory_lock(123):
        await asyncio.sleep(0.03)

    tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    assert all(task.done() for task in tasks)
    # The keepalive fired at least once during the 0.03s window.
    assert any("SELECT 1" in call for call in fake_engine.connection.executed)
