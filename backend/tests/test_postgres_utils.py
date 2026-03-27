import postgres_utils


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.closed = False

    def executemany(self, query, seq_of_params):
        self.calls.append((query, list(seq_of_params)))

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.execute_calls: list[tuple[str, object]] = []
        self.cursor_instance = _FakeCursor()

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        return False

    def execute(self, query, params=None):
        self.execute_calls.append((query, params))
        return "execute-result"

    def cursor(self):
        return self.cursor_instance


def test_connect_postgres_wraps_psycopg_connection_with_sqlite_like_surface(monkeypatch):
    fake_connection = _FakeConnection()
    captured = {}

    def fake_connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_connection

    monkeypatch.setattr(postgres_utils, "DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(postgres_utils, "connect", fake_connect)

    adapter = postgres_utils.connect_postgres(row_factory=None)

    assert captured == {
        "url": "postgresql://example",
        "kwargs": {"connect_timeout": postgres_utils.DATABASE_CONNECT_TIMEOUT_SECONDS},
    }
    assert adapter.execute("SELECT 1") == "execute-result"
    assert fake_connection.execute_calls == [("SELECT 1", None)]

    cursor = adapter.executemany("INSERT INTO t VALUES (%s)", [(1,), (2,)])
    assert cursor is fake_connection.cursor_instance
    assert fake_connection.cursor_instance.calls == [
        ("INSERT INTO t VALUES (%s)", [(1,), (2,)]),
    ]

    with adapter as wrapped:
        assert wrapped is adapter

    assert fake_connection.entered is True
    assert fake_connection.exited is True
