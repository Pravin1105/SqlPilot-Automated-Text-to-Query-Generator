import pytest
from sqlpilot.core.schema_inspector import SchemaInspector
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.db.sample_db_builder import seed_sample_database
from config import settings


@pytest.fixture(scope="module")
def schema():
    db_path = seed_sample_database(settings.db_path)
    return SchemaInspector(db_path).inspect()


def test_valid_select_query(schema):
    validator = SQLParserValidator(schema)
    result = validator.parse_and_validate("SELECT * FROM customers WHERE city = 'New York';")
    assert result.is_valid is True
    assert result.statement_type == "SELECT"
    assert "customers" in result.referenced_tables


def test_sqlite_master_system_table_allowed(schema):
    validator = SQLParserValidator(schema)
    result = validator.parse_and_validate("SELECT name FROM sqlite_master WHERE type='table';")
    assert result.is_valid is True
    assert result.statement_type == "SELECT"
    assert "sqlite_master" in result.referenced_tables


def test_invalid_table_reference(schema):
    validator = SQLParserValidator(schema)
    result = validator.parse_and_validate("SELECT * FROM non_existent_table;")
    assert result.is_valid is False
    assert "Invalid Table Reference" in result.error_message


def test_multi_statement_blocking(schema):
    validator = SQLParserValidator(schema)
    result = validator.parse_and_validate("SELECT * FROM customers; DROP TABLE orders;")
    assert result.is_valid is False
    assert "Multiple SQL statements are not allowed" in result.error_message


def test_malformed_syntax(schema):
    validator = SQLParserValidator(schema)
    result = validator.parse_and_validate("SELECT FROM WHERE;")
    assert result.is_valid is False
    assert "SQL Syntax Error" in result.error_message
