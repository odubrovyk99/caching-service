from tests.integration.database import (
    downgrade_to_base,
    fetch_table_names,
    fetch_unique_index_names,
    upgrade_to_head,
)

EXPECTED_TABLES = {"transformation", "payload"}
EXPECTED_UNIQUE_INDEXES = {"idx_transformation__input_hash", "idx_payload__input_hash"}


def test_upgrade_creates_tables_and_unique_indexes(postgres_url: str) -> None:
    assert fetch_table_names(postgres_url) >= EXPECTED_TABLES
    assert fetch_unique_index_names(postgres_url) >= EXPECTED_UNIQUE_INDEXES


def test_downgrade_drops_tables_and_upgrade_restores_them(postgres_url: str) -> None:
    downgrade_to_base(postgres_url)
    try:
        assert not EXPECTED_TABLES & fetch_table_names(postgres_url)
    finally:
        upgrade_to_head(postgres_url)

    assert fetch_unique_index_names(postgres_url) >= EXPECTED_UNIQUE_INDEXES
