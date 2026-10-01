"""Schema-aware RAG component combining local vector retrieval and relationship graph expansion.

Enforces zero-data privacy:
- Analyzes only metadata schema objects.
- Does not inspect database tables, rows, or records.
"""

import re
from typing import List, Set
from sqlpilot.core.schema_inspector import DatabaseSchema, TableSchema
from sqlpilot.core.schema_embedder import LocalSchemaVectorIndex


class SchemaRetriever:
    """Schema-aware RAG component retrieving relevant tables and relationships for a question."""

    def __init__(self, schema: DatabaseSchema):
        self.schema = schema
        self.vector_index = LocalSchemaVectorIndex(schema)

    def retrieve_relevant_schema(self, question: str) -> List[str]:
        """Given a question, retrieve table names relevant to the query context using local vector RAG."""
        # 1. Primary: Local Vector Similarity Retrieval (Offline TF-IDF + n-gram Cosine Similarity)
        vector_matched = set(
            self.vector_index.search_relevant_tables(
                question, similarity_threshold=0.08, expand_foreign_keys=True
            )
        )

        # 2. Secondary: Fast Domain / Synonym Fallback matching
        question_words = set(re.findall(r"\b\w+\b", question.lower()))
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

        synonym_matched: Set[str] = set()
        for word in question_words:
            if word in synonym_map:
                for target_t in synonym_map[word]:
                    if target_t in self.schema.tables:
                        synonym_matched.add(target_t)

        combined_matches: Set[str] = vector_matched.union(synonym_matched)

        # 3. Expand with 1-hop foreign key connectivity graph
        expanded_tables: Set[str] = set(combined_matches)
        for table_name in list(combined_matches):
            table: TableSchema = self.schema.tables.get(table_name)
            if not table:
                continue
            # Forward FKs
            for fk in table.foreign_keys:
                if fk.foreign_table.lower() in self.schema.tables:
                    expanded_tables.add(fk.foreign_table.lower())
            # Reverse FKs
            for other_name, other_table in self.schema.tables.items():
                for fk in other_table.foreign_keys:
                    if fk.foreign_table.lower() == table_name:
                        expanded_tables.add(other_name)

        if not expanded_tables:
            return list(self.schema.tables.keys())

        return sorted(list(expanded_tables))
