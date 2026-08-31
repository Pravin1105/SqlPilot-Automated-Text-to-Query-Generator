import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union


@dataclass(frozen=True)
class ColumnSchema:
    """Represents a single database column metadata."""

    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    default_value: Optional[str] = None


@dataclass(frozen=True)
class ForeignKeySchema:
    """Represents a foreign key constraint relationship."""

    column: str
    foreign_table: str
    foreign_column: str


@dataclass
class TableSchema:
    """Represents a single database table and its constraints."""

    name: str
    columns: List[ColumnSchema] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKeySchema] = field(default_factory=list)

    def get_column(self, col_name: str) -> Optional[ColumnSchema]:
        for col in self.columns:
            if col.name.lower() == col_name.lower():
                return col
        return None

    def to_prompt_str(self) -> str:
        """Render clean, minimal human-readable schema string for LLM context."""
        col_strs = []
        for col in self.columns:
            pk_suffix = " PRIMARY KEY" if col.is_primary_key else ""
            null_suffix = " NOT NULL" if not col.is_nullable and not col.is_primary_key else ""
            col_strs.append(f"  {col.name} {col.data_type}{pk_suffix}{null_suffix}")

        fk_strs = [
            f"  FOREIGN KEY ({fk.column}) REFERENCES {fk.foreign_table}({fk.foreign_column})"
            for fk in self.foreign_keys
        ]

        lines = [f"TABLE {self.name} ("]
        lines.extend(col_strs)
        if fk_strs:
            lines.extend(fk_strs)
        lines.append(");")
        return "\n".join(lines)


@dataclass
class DatabaseSchema:
    """Represents the complete database schema metadata."""

    database_path: str
    tables: Dict[str, TableSchema] = field(default_factory=dict)

    def get_table(self, table_name: str) -> Optional[TableSchema]:
        return self.tables.get(table_name.lower())

    def to_prompt_str(self, table_subset: Optional[List[str]] = None) -> str:
        """Render complete or subsetted schema description for LLM prompt."""
        target_tables = (
            [t.lower() for t in table_subset]
            if table_subset
            else list(self.tables.keys())
        )
        parts = []
        for name, table in self.tables.items():
            if name.lower() in target_tables:
                parts.append(table.to_prompt_str())
        return "\n\n".join(parts)


class SchemaInspector:
    """Inspects a relational database engine and builds a DatabaseSchema metadata object."""

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)

    def inspect(self) -> DatabaseSchema:
        """Perform deterministic schema inspection using SQLite PRAGMA commands."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file does not exist at path: {self.db_path}")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get list of user tables (excluding sqlite internal tables)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        tables: Dict[str, TableSchema] = {}

        for table_name in table_names:
            table_schema = TableSchema(name=table_name)

            # 1. Inspect Columns (PRAGMA table_info)
            cursor.execute(f"PRAGMA table_info({table_name});")
            # row format: (cid, name, type, notnull, dflt_value, pk)
            for row in cursor.fetchall():
                _, col_name, data_type, notnull, dflt_val, pk = row
                is_pk = bool(pk > 0)
                is_nullable = not bool(notnull) and not is_pk

                col_schema = ColumnSchema(
                    name=col_name,
                    data_type=data_type.upper(),
                    is_nullable=is_nullable,
                    is_primary_key=is_pk,
                    default_value=str(dflt_val) if dflt_val is not None else None,
                )
                table_schema.columns.append(col_schema)
                if is_pk:
                    table_schema.primary_keys.append(col_name)

            # 2. Inspect Foreign Keys (PRAGMA foreign_key_list)
            cursor.execute(f"PRAGMA foreign_key_list({table_name});")
            # row format: (id, seq, table, from, to, on_update, on_delete, match)
            for row in cursor.fetchall():
                _, _, foreign_table, from_col, to_col, _, _, _ = row
                fk_schema = ForeignKeySchema(
                    column=from_col,
                    foreign_table=foreign_table,
                    foreign_column=to_col,
                )
                table_schema.foreign_keys.append(fk_schema)

            tables[table_name.lower()] = table_schema

        conn.close()
        return DatabaseSchema(database_path=str(self.db_path), tables=tables)
