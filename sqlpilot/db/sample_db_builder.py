import sqlite3
from pathlib import Path
from typing import Union
from config import settings


def seed_sample_database(db_path: Union[str, Path] = settings.db_path) -> Path:
    """Create and seed the sample SQLite e-commerce database with realistic mock data."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB file to ensure clean reproducible seeding
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable Foreign Key enforcement in SQLite
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Customers Table
    cursor.execute(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT 'USA',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """
    )

    # 2. Products Table
    cursor.execute(
        """
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock_quantity INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """
    )

    # 3. Orders Table
    cursor.execute(
        """
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'shipped', 'cancelled')),
            total_amount REAL NOT NULL DEFAULT 0.0,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id) ON DELETE CASCADE
        );
    """
    )

    # 4. Order Items Table
    cursor.execute(
        """
        CREATE TABLE order_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products (product_id)
        );
    """
    )

    # 5. Payments Table
    cursor.execute(
        """
        CREATE TABLE payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL DEFAULT (datetime('now')),
            payment_method TEXT NOT NULL CHECK (payment_method IN ('credit_card', 'paypal', 'bank_transfer', 'apple_pay')),
            amount REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE CASCADE
        );
    """
    )

    # Seed Data Insertion
    cursor.executemany(
        """
        INSERT INTO customers (customer_id, first_name, last_name, email, city, state, country, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """,
        [
            (1, "Alice", "Smith", "alice@example.com", "New York", "NY", "USA", "2026-01-15 10:00:00"),
            (2, "Bob", "Jones", "bob@example.com", "Los Angeles", "CA", "USA", "2026-02-01 11:30:00"),
            (3, "Charlie", "Brown", "charlie@example.com", "Chicago", "IL", "USA", "2026-02-10 14:15:00"),
            (4, "Diana", "Prince", "diana@example.com", "Austin", "TX", "USA", "2026-03-05 09:45:00"),
            (5, "Ethan", "Hunt", "ethan@example.com", "Seattle", "WA", "USA", "2026-04-12 16:20:00"),
            (6, "Fiona", "Gallagher", "fiona@example.com", "Boston", "MA", "USA", "2026-05-18 13:00:00"),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO products (product_id, name, category, price, stock_quantity, created_at)
        VALUES (?, ?, ?, ?, ?, ?);
    """,
        [
            (101, "MacBook Pro 16", "Electronics", 2499.99, 25, "2026-01-01 00:00:00"),
            (102, "iPhone 15 Pro", "Electronics", 999.99, 50, "2026-01-01 00:00:00"),
            (103, "Wireless Headphones", "Accessories", 199.99, 100, "2026-01-01 00:00:00"),
            (104, "Ergonomic Chair", "Furniture", 349.50, 15, "2026-01-01 00:00:00"),
            (105, "Standing Desk", "Furniture", 599.00, 10, "2026-01-01 00:00:00"),
            (106, "Mechanical Keyboard", "Accessories", 129.99, 40, "2026-01-01 00:00:00"),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO orders (order_id, customer_id, order_date, status, total_amount)
        VALUES (?, ?, ?, ?, ?);
    """,
        [
            (1001, 1, "2026-06-01 10:15:00", "completed", 2699.98),
            (1002, 2, "2026-06-03 14:22:00", "completed", 999.99),
            (1003, 1, "2026-06-15 09:30:00", "completed", 199.99),
            (1004, 3, "2026-07-02 11:45:00", "shipped", 948.50),
            (1005, 4, "2026-07-10 16:10:00", "pending", 129.99),
            (1006, 5, "2026-08-01 12:00:00", "completed", 3499.97),
            (1007, 2, "2026-08-20 15:30:00", "cancelled", 349.50),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO order_items (item_id, order_id, product_id, quantity, unit_price)
        VALUES (?, ?, ?, ?, ?);
    """,
        [
            (1, 1001, 101, 1, 2499.99),
            (2, 1001, 103, 1, 199.99),
            (3, 1002, 102, 1, 999.99),
            (4, 1003, 103, 1, 199.99),
            (5, 1004, 104, 1, 349.50),
            (6, 1004, 105, 1, 599.00),
            (7, 1005, 106, 1, 129.99),
            (8, 1006, 101, 1, 2499.99),
            (9, 1006, 102, 1, 999.98),
            (10, 1007, 104, 1, 349.50),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO payments (payment_id, order_id, payment_date, payment_method, amount)
        VALUES (?, ?, ?, ?, ?);
    """,
        [
            (501, 1001, "2026-06-01 10:16:00", "credit_card", 2699.98),
            (502, 1002, "2026-06-03 14:23:00", "paypal", 999.99),
            (503, 1003, "2026-06-15 09:31:00", "apple_pay", 199.99),
            (504, 1004, "2026-07-02 11:46:00", "credit_card", 948.50),
            (505, 1006, "2026-08-01 12:01:00", "bank_transfer", 3499.97),
        ],
    )

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = seed_sample_database()
    print(f"Sample database successfully created and seeded at: {path.resolve()}")
