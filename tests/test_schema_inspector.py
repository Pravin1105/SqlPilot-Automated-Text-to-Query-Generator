import pytest
from config import settings
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.core.schema_inspector import SchemaInspector


@pytest.fixture(scope="module")
def seeded_db():
    db_path = settings.db_path
    seed_sample_database(db_path)
    return db_path


def test_schema_inspector_tables(seeded_db):
    inspector = SchemaInspector(seeded_db)
    schema = inspector.inspect()

    expected_tables = {"customers", "products", "orders", "order_items", "payments"}
    assert set(schema.tables.keys()) == expected_tables


def test_schema_inspector_customers_table(seeded_db):
    inspector = SchemaInspector(seeded_db)
    schema = inspector.inspect()

    customers = schema.get_table("customers")
    assert customers is not None
    assert "customer_id" in customers.primary_keys
    assert len(customers.columns) == 8

    email_col = customers.get_column("email")
    assert email_col is not None
    assert email_col.data_type == "TEXT"


def test_schema_inspector_foreign_keys(seeded_db):
    inspector = SchemaInspector(seeded_db)
    schema = inspector.inspect()

    orders = schema.get_table("orders")
    assert orders is not None
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].column == "customer_id"
    assert orders.foreign_keys[0].foreign_table == "customers"


def test_schema_prompt_str(seeded_db):
    inspector = SchemaInspector(seeded_db)
    schema = inspector.inspect()

    prompt_str = schema.to_prompt_str(table_subset=["customers", "orders"])
    assert "TABLE customers" in prompt_str
    assert "TABLE orders" in prompt_str
    assert "TABLE products" not in prompt_str
