# SQLPilot — Project Context & System Specification

**SQLPilot** is a local, schema-aware, AI-assisted database interface that converts natural language requests into SQL and safely executes them against a relational database using deterministic validation, safety classification, human authorization, and controlled execution.

---

## Codebase Principles: Senior Developer Standard

> [!IMPORTANT]
> **Minimalism, Simplicity & Elegance**:
> - **Zero Bloat / Over-Engineering**: Clean, readable Python with zero enterprise fluff or unnecessary design pattern noise.
> - **Self-Documenting & Typed**: Fully type-hinted, explicit data structures (`dataclasses` / `Pydantic`), concise docstrings.
> - **Auditability**: Every stage of the pipeline (`schema` -> `rag` -> `llm` -> `parser` -> `safety` -> `gate` -> `execution`) is isolated in a small, single-responsibility module that a senior engineer can review in minutes.

---

## Architecture & Security Principles

> **Core Security Principle**: The LLM generates a proposed database action. It is NEVER given execution authority. Every query is treated as untrusted input.

### Execution Control Flow

```text
User's Plain-English Request
        ↓
Database Schema Inspection
        ↓
Relevant Schema Retrieval (RAG)
        ↓
Gemini LLM (via Provider Abstraction)
        ↓
SQL Generation
        ↓
SQL Parsing & Validation (SQLGlot AST)
        ↓
Safety Classification (READ, DML, DDL, DESTRUCTIVE, UNKNOWN)
        ↓
 ┌───────────────────────┐
 │                       │
READ-ONLY            Modification (DML / DDL / DESTRUCTIVE)
 │                       │
 ↓                       ↓
Execute          Explain + Ask Permission (Human-in-the-Loop Gate)
                         ↓
                  User Approves?
                    ↙       ↘
                  YES        NO
                   ↓          ↓
                Execute     Cancel
```

---

## Core System Modules

1. **Schema Engine & RAG Retrieval**
   - Automatically inspects tables, columns, data types, primary keys, foreign keys, and relationships.
   - Retrieves only relevant schema components for a given question instead of passing entire schemas to the LLM.

2. **LLM Provider Abstraction**
   - Clean provider interface for Gemini API (expandable to Ollama / local models).
   - Structured output generation for SQL, explanation, and ambiguity detection.

3. **SQL Parsing & Validation (`sqlglot`)**
   - Deterministic AST parsing (verifying syntax, table references, column validity, multi-statement blocking).

4. **Safety Classifier & Human-in-the-Loop Gate**
   - Classifies queries into `READ`, `DML`, `DDL`, `DESTRUCTIVE`, `UNKNOWN`.
   - `READ`: Auto-executes after passing validation.
   - `DML` / `DDL`: Prompts user with structured impact assessment (`[Y] Yes / [N] No`).
   - `DESTRUCTIVE` (`DROP`, `TRUNCATE`): Displays high-visibility warning alert before asking for explicit confirmation.
   - `UNKNOWN` / Failed validation: Automatically blocked.

5. **Self-Correction Retry Loop**
   - Captures database runtime errors, feeds tracebacks back to Gemini, and re-routes generated fixes back through the full validation and safety pipeline (max N attempts).

6. **Ambiguity Resolution Engine**
   - Detects underspecified or multi-interpretative requests and prompts the user with explicit choices rather than guessing.

7. **Evaluation Benchmark Suite**
   - 50–100 benchmark natural language test queries covering simple selects, joins, aggregations, date math, DML, DDL, destructive queries, and ambiguous prompts.
   - Measures: SQL correctness, execution success, schema retrieval relevance, correction success, safety accuracy, latency, and token usage.

---

## Tech Stack

- **Language**: Python 3.11+ (clean, idiomatic, fully type-hinted)
- **Database Engine**: SQLite (embedded, local)
- **ORM / Introspection**: SQLAlchemy / SQLite PRAGMA
- **SQL Parsing**: SQLGlot
- **Data Validation & Settings**: Pydantic v2
- **LLM Integration**: Google Gemini API (via clean LLM Provider abstraction)
- **CLI / UI**: Typer + Rich
- **Testing & Benchmarking**: Pytest + custom benchmark runner

---

## 15-Step Development Roadmap

1. SQLite sample database (`customers`, `products`, `orders`, `order_items`, `payments`)
2. Schema inspector & metadata builder
3. Typer + Rich CLI framework
4. Gemini provider abstraction integration
5. Basic English → SQL generator
6. SQLGlot parser + validator
7. Query safety classifier (`READ`, `DML`, `DDL`, `DESTRUCTIVE`, `UNKNOWN`)
8. Human-in-the-loop permission gate
9. Safe query execution engine
10. Error analysis & self-correction loop
11. Schema retrieval / RAG engine
12. Benchmark evaluation framework (50–100 test queries)
13. Observability, logging & metrics engine
14. Documentation, tests, and CLI demonstration
15. (Optional) Future VS Code extension integration API
