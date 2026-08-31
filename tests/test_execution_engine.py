import pytest
from config import settings
from sqlpilot.core.execution_engine import ExecutionEngine
from sqlpilot.db.sample_db_builder import seed_sample_database


@pytest.fixture(scope="module")
def db_engine():
    db_path = seed_sample_database(settings.db_path)
    return ExecutionEngine(db_path)


def test_execute_select_query(db_engine):
    res = db_engine.execute("SELECT customer_id, first_name, city FROM customers ORDER BY customer_id ASC LIMIT 2;")
    assert res.success is True
    assert len(res.rows) == 2
    assert res.columns == ["customer_id", "first_name", "city"]
    assert res.rows[0]["first_name"] == "Alice"


def test_execute_insert_query(db_engine):
    res = db_engine.execute(
        "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Sam', 'Altman', 'sam@example.com', 'San Francisco', 'CA');"
    )
    assert res.success is True
    assert res.affected_row_count == 1

    # Verify insertion
    verify_res = db_engine.execute("SELECT * FROM customers WHERE email = 'sam@example.com';")
    assert verify_res.success is True
    assert len(verify_res.rows) == 1
    assert verify_res.rows[0]["first_name"] == "Sam"


def test_execute_invalid_sql_returns_error(db_engine):
    res = db_engine.execute("SELECT * FROM non_existent_table;")
    assert res.success is False
    assert res.error_message is not None
    assert "no such table" in res.error_message.lower()
