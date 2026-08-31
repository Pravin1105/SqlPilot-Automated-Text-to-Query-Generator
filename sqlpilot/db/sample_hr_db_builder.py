import sqlite3
from pathlib import Path
from typing import Union
from config import settings


def seed_sample_hr_database(db_path: Union[str, Path] = settings.data_dir / "sample_hr.db") -> Path:
    """Create and seed a second sample database (HR domain) to test multi-DB switching."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Departments Table
    cursor.execute(
        """
        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            location TEXT NOT NULL,
            budget REAL NOT NULL DEFAULT 0.0
        );
    """
    )

    # 2. Employees Table
    cursor.execute(
        """
        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            department_id INTEGER NOT NULL,
            salary REAL NOT NULL,
            hire_date TEXT NOT NULL DEFAULT (date('now')),
            FOREIGN KEY (department_id) REFERENCES departments (department_id)
        );
    """
    )

    # 3. Projects Table
    cursor.execute(
        """
        CREATE TABLE projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            budget REAL NOT NULL,
            FOREIGN KEY (department_id) REFERENCES departments (department_id)
        );
    """
    )

    # Insert Data
    cursor.executemany(
        """
        INSERT INTO departments (department_id, name, location, budget)
        VALUES (?, ?, ?, ?);
    """,
        [
            (1, "Engineering", "San Francisco", 1500000.00),
            (2, "Marketing", "New York", 500000.00),
            (3, "Human Resources", "Austin", 300000.00),
            (4, "Sales", "Chicago", 800000.00),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO employees (employee_id, first_name, last_name, email, department_id, salary, hire_date)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """,
        [
            (101, "Alice", "Engineer", "alice.eng@example.com", 1, 140000.00, "2024-01-15"),
            (102, "Bob", "Coder", "bob.coder@example.com", 1, 125000.00, "2024-03-01"),
            (103, "Carol", "Marketer", "carol.mark@example.com", 2, 95000.00, "2024-05-10"),
            (104, "Dave", "Recruiter", "dave.hr@example.com", 3, 85000.00, "2025-02-01"),
            (105, "Eve", "Salesrep", "eve.sales@example.com", 4, 110000.00, "2025-06-15"),
        ],
    )

    cursor.executemany(
        """
        INSERT INTO projects (project_id, name, department_id, budget)
        VALUES (?, ?, ?, ?);
    """,
        [
            (1, "Cloud Migration", 1, 500000.00),
            (2, "Q3 Rebranding", 2, 150000.00),
            (3, "Global Expansion", 4, 300000.00),
        ],
    )

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = seed_sample_hr_database()
    print(f"Sample HR database seeded successfully at: {path.resolve()}")
