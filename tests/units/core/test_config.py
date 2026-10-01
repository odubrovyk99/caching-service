import pytest

from caching_service.core.config import Settings

POSTGRES_ENV = {
    "POSTGRES_HOST": "db.internal",
    "POSTGRES_PORT": "6543",
    "POSTGRES_USER": "cache",
    "POSTGRES_PASSWORD": "secret",
    "POSTGRES_DB": "caching",
}


@pytest.fixture
def postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in POSTGRES_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("postgres_env")
def test_reads_unprefixed_postgres_variables() -> None:
    settings = Settings()

    assert settings.postgres_host == "db.internal"
    assert settings.postgres_port == 6543
    assert settings.postgres_user == "cache"
    assert settings.postgres_password.get_secret_value() == "secret"
    assert settings.postgres_db == "caching"


@pytest.mark.usefixtures("postgres_env")
def test_builds_an_asyncpg_url_from_the_parts() -> None:
    url = Settings().database_url

    assert url.render_as_string(hide_password=False) == "postgresql+asyncpg://cache:secret@db.internal:6543/caching"


@pytest.mark.usefixtures("postgres_env")
def test_password_with_url_special_characters_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd?#")

    assert Settings().database_url.password == "p@ss:w/rd?#"


@pytest.mark.usefixtures("postgres_env")
def test_password_is_hidden_in_repr() -> None:
    assert "secret" not in repr(Settings())


def test_host_and_port_have_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.setenv(name, POSTGRES_ENV[name])
    for name in ("POSTGRES_HOST", "POSTGRES_PORT"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432


@pytest.mark.usefixtures("postgres_env")
def test_log_level_reads_unprefixed_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    assert Settings().log_level == "DEBUG"
