import pytest
from config import settings
from sqlpilot.core.connection_manager import ConnectionManager
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.db.sample_hr_db_builder import seed_sample_hr_database


class MockLLMProvider:
    """Mock LLM Provider for testing connection manager without network calls."""

    def generate_json(self, prompt: str, system_instruction: str = None):
        return {"sql": "SELECT 1;", "explanation": "Test"}


@pytest.fixture(scope="module")
def seeded_databases():
    store_path = seed_sample_database(settings.db_path)
    hr_path = seed_sample_hr_database(settings.data_dir / "sample_hr.db")
    return store_path, hr_path


def test_initial_connect(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())

    ok, msg = conn.connect("sample_store.db")
    assert ok is True
    assert conn.is_connected is True
    assert "sample_store.db" in msg
    assert "customers" in conn.schema.tables


def test_connect_when_already_connected_fails(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())
    conn.connect("sample_store.db")

    # Attempting to connect again without disconnecting first MUST fail
    ok, msg = conn.connect("sample_hr.db")
    assert ok is False
    assert "Already connected to" in msg
    assert "You must run 'disconnect" in msg
    assert conn.db_path.name == "sample_store.db"


def test_connect_non_existent_db_fails(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())

    ok, msg = conn.connect("non_existent_database.db")
    assert ok is False
    assert "Database Error: Database file 'non_existent_database.db' does not exist." in msg
    assert conn.is_connected is False


def test_disconnect_with_typo_fails_and_retains_connection(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())
    conn.connect("sample_store.db")

    # Typing a typo like sample_store.dc MUST fail and retain connection to sample_store.db
    ok, msg = conn.disconnect("sample_store.dc")
    assert ok is False
    assert "Disconnect Error" in msg
    assert "does not match currently connected database" in msg
    assert conn.is_connected is True
    assert conn.db_path.name == "sample_store.db"


def test_disconnect_successful_message(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())
    conn.connect("sample_store.db")

    ok, msg = conn.disconnect("sample_store.db")
    assert ok is True
    assert "Successfully disconnected from 'sample_store.db'" in msg
    assert conn.is_connected is False
    assert conn.db_path is None


def test_two_step_switch_workflow(seeded_databases):
    conn = ConnectionManager(MockLLMProvider())

    # Step 1: Connect to store DB
    ok1, _ = conn.connect("sample_store.db")
    assert ok1 is True
    assert "customers" in conn.schema.tables

    # Step 2: Disconnect first
    ok2, msg2 = conn.disconnect("sample_store.db")
    assert ok2 is True
    assert "Successfully disconnected" in msg2
    assert conn.is_connected is False

    # Step 3: Connect to HR DB
    ok3, msg3 = conn.connect("sample_hr.db")
    assert ok3 is True
    assert conn.is_connected is True
    assert conn.db_path.name == "sample_hr.db"
    assert "employees" in conn.schema.tables
    assert "departments" in conn.schema.tables
    assert "customers" not in conn.schema.tables
