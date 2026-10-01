"""Local Schema Chunking, Vector Embedding, and Offline Retrieval Engine.

Ensures strict privacy:
- Operates 100% locally and offline (zero external API calls or model downloads).
- Inspects and chunks only structural schema metadata (tables, columns, types, primary/foreign keys).
- NEVER embeds or accesses database records, tuples, or row contents.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlpilot.core.schema_inspector import DatabaseSchema, TableSchema


@dataclass
class SchemaChunk:
    """Represents an isolated structural chunk of database schema metadata."""

    chunk_id: str
    table_name: str
    chunk_type: str  # "table_summary", "column_definition", "foreign_key_relation"
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class LocalTFIDFEmbedder:
    """Lightweight, 100% offline local vector embedder using subword n-grams and TF-IDF."""

    def __init__(self, ngram_range: Tuple[int, int] = (3, 4)):
        self.ngram_range = ngram_range
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.is_fitted: bool = False

    def _extract_features(self, text: str) -> List[str]:
        """Extract word tokens and character n-grams from text."""
        clean_text = text.lower()
        words = re.findall(r"\b[a-z0-9_]+\b", clean_text)
        features = list(words)

        # Add character n-grams for typo tolerance and morphological similarity
        for word in words:
            if len(word) >= 3:
                for n in range(self.ngram_range[0], min(self.ngram_range[1] + 1, len(word) + 1)):
                    for i in range(len(word) - n + 1):
                        features.append(word[i : i + n])

        return features

    def fit(self, documents: List[str]) -> "LocalTFIDFEmbedder":
        """Compute vocabulary and inverse document frequencies across chunk corpus."""
        doc_count = len(documents)
        if doc_count == 0:
            return self

        doc_frequencies: Counter = Counter()
        all_features: Set[str] = set()

        for doc in documents:
            unique_doc_feats = set(self._extract_features(doc))
            for feat in unique_doc_feats:
                doc_frequencies[feat] += 1
                all_features.add(feat)

        self.vocabulary = {feat: idx for idx, feat in enumerate(sorted(all_features))}
        self.idf = {
            feat: math.log((1.0 + doc_count) / (1.0 + doc_frequencies[feat])) + 1.0
            for feat in all_features
        }
        self.is_fitted = True
        return self

    def embed(self, text: str) -> Dict[int, float]:
        """Convert text into a sparse L2-normalized vector embedding."""
        if not self.is_fitted or not text.strip():
            return {}

        features = self._extract_features(text)
        if not features:
            return {}

        counts = Counter(features)
        vector: Dict[int, float] = {}

        for feat, count in counts.items():
            if feat in self.vocabulary:
                idx = self.vocabulary[feat]
                tf = 1.0 + math.log(count)
                vector[idx] = tf * self.idf.get(feat, 1.0)

        # L2 Normalization
        norm = math.sqrt(sum(v * v for v in vector.values()))
        if norm > 0:
            for idx in vector:
                vector[idx] /= norm

        return vector

    @staticmethod
    def cosine_similarity(vec_a: Dict[int, float], vec_b: Dict[int, float]) -> float:
        """Compute cosine similarity between two sparse normalized vectors."""
        if not vec_a or not vec_b:
            return 0.0

        # Dot product of smaller into larger
        if len(vec_a) > len(vec_b):
            vec_a, vec_b = vec_b, vec_a

        return sum(val * vec_b.get(idx, 0.0) for idx, val in vec_a.items())


class SchemaChunker:
    """Deconstructs database schema metadata into semantic chunks."""

    @staticmethod
    def chunk_schema(schema: DatabaseSchema) -> List[SchemaChunk]:
        """Deconstruct schema into table, column, and relationship chunks.

        GUARANTEE: Only structural metadata is chunked. Zero database records or tuples.
        """
        chunks: List[SchemaChunk] = []

        for table_name, table in schema.tables.items():
            col_names = [col.name for col in table.columns]
            pk_names = table.primary_keys
            fk_summaries = [
                f"{fk.column} -> {fk.foreign_table}.{fk.foreign_column}"
                for fk in table.foreign_keys
            ]

            # 1. High-level Table Summary Chunk
            summary_content = (
                f"Table {table_name}: Contains columns {', '.join(col_names)}. "
                f"Primary key: {', '.join(pk_names) if pk_names else 'None'}. "
                f"Foreign key links: {', '.join(fk_summaries) if fk_summaries else 'None'}."
            )
            chunks.append(
                SchemaChunk(
                    chunk_id=f"table::{table_name}",
                    table_name=table_name,
                    chunk_type="table_summary",
                    content=summary_content,
                    metadata={"columns": col_names, "pks": pk_names},
                )
            )

            # 2. Detailed Column Attribute Chunks
            col_details = []
            for col in table.columns:
                pk_tag = " (PRIMARY KEY)" if col.is_primary_key else ""
                nullable_tag = " NULL" if col.is_nullable else " NOT NULL"
                col_details.append(f"{col.name} {col.data_type}{pk_tag}{nullable_tag}")

            col_chunk_content = (
                f"Columns for table {table_name}: " + "; ".join(col_details)
            )
            chunks.append(
                SchemaChunk(
                    chunk_id=f"columns::{table_name}",
                    table_name=table_name,
                    chunk_type="column_definition",
                    content=col_chunk_content,
                    metadata={"column_count": len(table.columns)},
                )
            )

            # 3. Foreign Key Relationship Chunks
            for fk in table.foreign_keys:
                rel_content = (
                    f"Relationship: Table {table_name} column {fk.column} references "
                    f"foreign table {fk.foreign_table} on column {fk.foreign_column}. "
                    f"Enables JOIN between {table_name} and {fk.foreign_table} on {table_name}.{fk.column} = {fk.foreign_table}.{fk.foreign_column}."
                )
                chunks.append(
                    SchemaChunk(
                        chunk_id=f"fk::{table_name}::{fk.column}::{fk.foreign_table}",
                        table_name=table_name,
                        chunk_type="foreign_key_relation",
                        content=rel_content,
                        metadata={
                            "source_table": table_name,
                            "foreign_table": fk.foreign_table,
                            "source_column": fk.column,
                            "foreign_column": fk.foreign_column,
                        },
                    )
                )

        return chunks


class LocalSchemaVectorIndex:
    """In-memory vector index for local schema chunks with relationship graph expansion."""

    def __init__(self, schema: DatabaseSchema):
        self.schema = schema
        self.chunker = SchemaChunker()
        self.embedder = LocalTFIDFEmbedder()
        self.chunks: List[SchemaChunk] = []
        self.chunk_embeddings: List[Dict[int, float]] = []
        self._build_index()

    def _build_index(self):
        """Chunk the schema and compute local vector embeddings."""
        self.chunks = self.chunker.chunk_schema(self.schema)
        documents = [chunk.content for chunk in self.chunks]
        self.embedder.fit(documents)
        self.chunk_embeddings = [self.embedder.embed(doc) for doc in documents]

    def search_relevant_tables(
        self,
        query: str,
        similarity_threshold: float = 0.08,
        expand_foreign_keys: bool = True,
    ) -> List[str]:
        """Search schema vector index for tables relevant to user question."""
        if not query.strip() or not self.chunks:
            return list(self.schema.tables.keys())

        query_vec = self.embedder.embed(query)
        scored_chunks: List[Tuple[float, SchemaChunk]] = []

        for idx, chunk in enumerate(self.chunks):
            chunk_vec = self.chunk_embeddings[idx]
            sim = self.embedder.cosine_similarity(query_vec, chunk_vec)
            if sim > 0:
                scored_chunks.append((sim, chunk))

        # Sort descending by similarity
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        matched_tables: Set[str] = set()
        for sim, chunk in scored_chunks:
            if sim >= similarity_threshold:
                matched_tables.add(chunk.table_name.lower())
                # If chunk is a foreign key relation, include referenced foreign table
                if chunk.chunk_type == "foreign_key_relation":
                    target_table = chunk.metadata.get("foreign_table")
                    if target_table and target_table.lower() in self.schema.tables:
                        matched_tables.add(target_table.lower())

        # Expand with 1-hop foreign key relationships (connectivity graph)
        if expand_foreign_keys and matched_tables:
            expanded = set(matched_tables)
            for t_name in list(matched_tables):
                t_schema = self.schema.tables.get(t_name)
                if t_schema:
                    # Forward FKs
                    for fk in t_schema.foreign_keys:
                        if fk.foreign_table.lower() in self.schema.tables:
                            expanded.add(fk.foreign_table.lower())
                    # Reverse FKs (tables pointing to this table)
                    for other_name, other_schema in self.schema.tables.items():
                        for fk in other_schema.foreign_keys:
                            if fk.foreign_table.lower() == t_name:
                                expanded.add(other_name.lower())
            matched_tables = expanded

        # Fallback to full schema if no high-confidence matches found
        if not matched_tables:
            return list(self.schema.tables.keys())

        return list(matched_tables)
