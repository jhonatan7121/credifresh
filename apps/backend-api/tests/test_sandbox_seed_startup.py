import pytest

from scripts import check_empty_sandbox_database as guard


def configure(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_SANDBOX_SEED_DATA", "true")
    monkeypatch.setenv("WOMPI_SANDBOX_SEED_NEW_DISPOSABLE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:synthetic@127.0.0.1/credifresh_test_db")


@pytest.mark.parametrize("key", ["ENVIRONMENT", "WOMPI_ENVIRONMENT", "WOMPI_SANDBOX_SEED_DATA", "WOMPI_SANDBOX_SEED_NEW_DISPOSABLE"])
def test_disposable_seed_requires_explicit_opt_in(monkeypatch, key):
    configure(monkeypatch)
    monkeypatch.delenv(key)
    monkeypatch.setattr(guard, "create_engine", lambda *args: pytest.fail("No debe conectar"))
    with pytest.raises(SystemExit):
        guard.main()


def test_disposable_seed_refuses_existing_tables(monkeypatch):
    configure(monkeypatch)
    class Engine:
        def dispose(self): pass
    class Inspector:
        def get_schema_names(self): return ["public"]
        def get_table_names(self, schema=None): return ["alembic_version"]
    monkeypatch.setattr(guard, "create_engine", lambda _: Engine())
    monkeypatch.setattr(guard, "inspect", lambda _: Inspector())
    with pytest.raises(SystemExit, match="existing database"):
        guard.main()


def test_disposable_seed_accepts_empty_isolated_database(monkeypatch):
    configure(monkeypatch)
    class Engine:
        def dispose(self): pass
    class Inspector:
        def get_schema_names(self): return ["public"]
        def get_table_names(self, schema=None): return []
        def get_view_names(self, schema=None): return []
    monkeypatch.setattr(guard, "create_engine", lambda _: Engine())
    monkeypatch.setattr(guard, "inspect", lambda _: Inspector())
    guard.main()
