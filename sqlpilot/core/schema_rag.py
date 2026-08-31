import re
from typing import List, Set
from sqlpilot.core.schema_inspector import DatabaseSchema, TableSchema


class SchemaRetriever:
    """Schema-aware RAG component retrieving relevant tables and relationships for a question."""

    def __init__(self, schema: DatabaseSchema):
        self.schema = schema

    def retrieve_relevant_schema(self, question: str) -> List[str]:
        """Given a question, retrieve table names relevant to the query context."""
        question_words = set(re.findall(r"\b\w+\b", question.lower()))
        matched_tables: Set[str] = set()

        for table_name, table in self.schema.tables.items():
            # 1. Match table name directly
            if table_name.lower() in question_words or table_name.lower()[:-1] in question_words:
                matched_tables.add(table_name.lower())
                continue

            # 2. Match column names or common domain synonyms
            for col in table.columns:
                col_lower = col.name.lower()
                if col_lower in question_words:
                    matched_tables.add(table_name.lower())
                    break

        # Keyword / Synonym Domain Fallbacks
        synonym_map = {
            "spend": ["customers", "orders", "order_items", "payments"],
            "spent": ["customers", "orders", "order_items", "payments"],
            "customer": ["customers"],
            "client": ["customers"],
            "buyer": ["customers"],
            "purchase": ["orders", "order_items"],
            "bought": ["orders", "order_items"],
            "revenue": ["orders", "payments"],
            "sales": ["orders", "order_items"],
            "product": ["products"],
            "item": ["products", "order_items"],
            "inventory": ["products"],
            "stock": ["products"],
            "pay": ["payments"],
            "payment": ["payments"],
            "method": ["payments"],
        }

        for word in question_words:
            if word in synonym_map:
                for target_t in synonym_map[word]:
                    if target_t in self.schema.tables:
                        matched_tables.add(target_t)

        # Expand Matched Set with Foreign Key Relationships (1-hop connectivity)
        expanded_tables: Set[str] = set(matched_tables)
        for table_name in list(matched_tables):
            table: TableSchema = self.schema.tables[table_name]
            # Include tables this table references
            for fk in table.foreign_keys:
                if fk.foreign_table.lower() in self.schema.tables:
                    expanded_tables.add(fk.foreign_table.lower())
            # Include tables referencing this table
            for other_name, other_table in self.schema.tables.items():
                for fk in other_table.foreign_keys:
                    if fk.foreign_table.lower() == table_name:
                        expanded_tables.add(other_name)

        # If no specific matches found, fallback to full schema
        if not expanded_tables:
            return list(self.schema.tables.keys())

        return list(expanded_tables)
