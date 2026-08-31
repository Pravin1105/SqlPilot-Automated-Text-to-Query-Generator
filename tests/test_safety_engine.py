import pytest
from sqlpilot.core.safety_engine import SafetyEngine, SafetyLevel
from sqlpilot.core.sql_parser import SQLParserValidator


def test_select_classified_as_read():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate("SELECT first_name, last_name FROM customers;")
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.READ
    assert classification.requires_approval is False


def test_insert_classified_as_dml():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate(
        "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Jane', 'Doe', 'jane@example.com', 'Miami', 'FL');"
    )
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.DML
    assert classification.requires_approval is True
    assert classification.is_destructive is False


def test_alter_classified_as_ddl():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate("ALTER TABLE customers ADD COLUMN phone TEXT;")
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.DDL
    assert classification.requires_approval is True


def test_drop_classified_as_destructive():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate("DROP TABLE orders;")
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.DESTRUCTIVE
    assert classification.requires_approval is True
    assert classification.is_destructive is True


def test_unrestricted_delete_classified_as_destructive():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate("DELETE FROM orders;")
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.DESTRUCTIVE
    assert classification.requires_approval is True
    assert classification.is_destructive is True


def test_restricted_delete_classified_as_dml():
    validator = SQLParserValidator()
    val_res = validator.parse_and_validate("DELETE FROM orders WHERE status = 'cancelled';")
    classification = SafetyEngine.classify(val_res)
    assert classification.level == SafetyLevel.DML
    assert classification.requires_approval is True
    assert classification.is_destructive is False
