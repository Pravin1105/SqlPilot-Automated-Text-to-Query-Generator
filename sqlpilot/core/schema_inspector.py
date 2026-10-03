import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass(frozen=True)
class ColumnSchema:
    """Represents a single database column metadata."""

    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    default_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "is_nullable": self.is_nullable,
            "is_primary_key": self.is_primary_key,
            "is_unique": self.is_unique,
            "default_value": self.default_value,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ColumnSchema":
        return cls(
            name=d["name"],
            data_type=d.get("data_type") or d.get("type") or "TEXT",
            is_nullable=d.get("is_nullable", not d.get("is_not_null", False)),
            is_primary_key=d.get("is_primary_key", False),
            is_unique=d.get("is_unique", False),
            default_value=d.get("default_value"),
        )


@dataclass(frozen=True)
class ForeignKeySchema:
    """Represents a foreign key constraint relationship."""

    column: str
    foreign_table: str
    foreign_column: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "foreign_table": self.foreign_table,
            "foreign_column": self.foreign_column,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ForeignKeySchema":
        return cls(
            column=d["column"],
            foreign_table=d["foreign_table"],
            foreign_column=d["foreign_column"],
        )


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TableSchema":
        cols = [ColumnSchema.from_dict(c) for c in d.get("columns", [])]
        fks = []
        for fk in d.get("foreign_keys", []):
            if isinstance(fk, dict):
                fks.append(ForeignKeySchema.from_dict(fk))
            elif isinstance(fk, str):
                import re
                m = re.match(r"^(\w+)\((\w+)\)$", fk.strip())
                if m:
                    fks.append(ForeignKeySchema(column="", foreign_table=m.group(1), foreign_column=m.group(2)))
        for c in d.get("columns", []):
            fk_str = c.get("foreign_key")
            if fk_str and isinstance(fk_str, str):
                import re
                m = re.match(r"^(\w+)\((\w+)\)$", fk_str.strip())
                if m and not any(f.column.lower() == c["name"].lower() for f in fks):
                    fks.append(ForeignKeySchema(
                        column=c["name"],
                        foreign_table=m.group(1),
                        foreign_column=m.group(2)
                    ))
        pks = d.get("primary_keys", [])
        if not pks:
            pks = [c.name for c in cols if c.is_primary_key]
        return cls(
            name=d["name"],
            columns=cols,
            primary_keys=list(pks),
            foreign_keys=fks,
        )

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "database": Path(self.database_path).name if self.database_path else "database.db",
            "database_path": self.database_path,
            "tables": [t.to_dict() for t in self.tables.values()],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DatabaseSchema":
        db_path = d.get("database_path", d.get("database", "database.db"))
        tables: Dict[str, TableSchema] = {}
        raw_tables = d.get("tables", [])
        if isinstance(raw_tables, dict):
            for k, t_data in raw_tables.items():
                t = TableSchema.from_dict(t_data)
                tables[t.name.lower()] = t
        elif isinstance(raw_tables, list):
            for t_data in raw_tables:
                t = TableSchema.from_dict(t_data)
                tables[t.name.lower()] = t
        return cls(database_path=str(db_path), tables=tables)

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

            # Discover unique single-column constraints/indexes
            unique_cols = set()
            try:
                cursor.execute(f"PRAGMA index_list({table_name});")
                # format: (seq, name, unique, origin, partial)
                for idx_row in cursor.fetchall():
                    if bool(idx_row[2]):  # unique == 1
                        idx_name = idx_row[1]
                        cursor.execute(f"PRAGMA index_info({idx_name});")
                        idx_cols = cursor.fetchall()
                        if len(idx_cols) == 1:
                            unique_cols.add(idx_cols[0][2].lower())
            except Exception:
                pass

            # 1. Inspect Columns (PRAGMA table_info)
            cursor.execute(f"PRAGMA table_info({table_name});")
            # row format: (cid, name, type, notnull, dflt_value, pk)
            for row in cursor.fetchall():
                _, col_name, data_type, notnull, dflt_val, pk = row
                is_pk = bool(pk > 0)
                is_nullable = not bool(notnull) and not is_pk
                is_unique = (col_name.lower() in unique_cols) and not is_pk

                col_schema = ColumnSchema(
                    name=col_name,
                    data_type=data_type.upper(),
                    is_nullable=is_nullable,
                    is_primary_key=is_pk,
                    is_unique=is_unique,
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
