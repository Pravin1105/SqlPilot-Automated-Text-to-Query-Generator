# SQLPilot — Living Memory & Project State

This file tracks the evolving project memory, technical design decisions, architecture standards, and implementation progress for **SQLPilot**.

---

## 1. Project Identity & Purpose

- **Name**: SQLPilot
- **Tagline**: A schema-aware, AI-assisted database interface that converts natural language into SQL while using deterministic validation, safety classification, human authorization, and controlled execution to make LLM-generated database operations reliable.
- **Key Differentiator**: Not a generic chatbot. The core value is the deterministic execution and safety pipeline around the probabilistic LLM.

---

## 2. Core Architectural Principles

> [!IMPORTANT]
> **Senior Developer Codebase Standard**:
> - **Minimalism & Elegance**: Clean, readable Python 3.11+ with zero enterprise fluff or over-engineering.
> - **Strict Security Boundary**: The LLM output is untrusted input. The LLM has zero execution authority.
> - **Failsafe Design**: If SQL parsing fails or safety classification is `UNKNOWN`, execution is blocked immediately.

### Pipeline Flow

```text
User Natural Language Request ($ sqlpilot)
                ↓
    Database Schema Inspection (`SchemaInspector`)
                ↓
  Schema RAG Retrieval (`SchemaRetriever` - Relevant subsetting)
                ↓
    LLM Integration (Gemini API via LLM Provider, `gemini-3.6-flash` default)
                ↓
 SQL Parsing & AST Validation (`SQLParserValidator` using SQLGlot)
                ↓
 Safety Classifier (`SafetyEngine`: READ, DML, DDL, DESTRUCTIVE, UNKNOWN)
                ↓
 ┌──────────────────────┐
 │                      │
READ                MODIFICATION / DESTRUCTIVE
 │                      │
 ↓                      ↓
Execute        Human Approval Gate (`PermissionGate` Rich UI)
                        │
                 User Approves?
                   ├── YES ──> Safe Execution (`ExecutionEngine`)
                   └── NO  ──> Cancel Execution
```

---

## 3. Implemented Modules & Architecture

| Module | File | Responsibility |
| :--- | :--- | :--- |
| **Config** | `config.py` | Pydantic Settings for paths, Gemini API keys, models, and retry caps. |
| **Database Seeder** | `sqlpilot/db/sample_db_builder.py` | Creates and seeds a realistic 5-table SQLite database (`customers`, `products`, `orders`, `order_items`, `payments`). |
| **Schema Inspector** | `sqlpilot/core/schema_inspector.py` | Deterministic SQLite PRAGMA inspection returning dataclass metadata (`TableSchema`, `ColumnSchema`, `ForeignKeySchema`). |
| **Schema RAG** | `sqlpilot/core/schema_rag.py` | Subsets schema tables based on keyword/synonym domain mapping and 1-hop FK graph traversal. |
| **LLM Provider** | `sqlpilot/core/llm_provider.py` | `GeminiLLMProvider` using official `google-genai` SDK with JSON structured output. |
| **SQL Generator** | `sqlpilot/core/sql_generator.py` | Builds dialect prompts, handles ambiguity detection, and calls LLMProvider. |
| **SQL Parser & Validator** | `sqlpilot/core/sql_parser.py` | `SQLGlot` AST parser checking syntax, single-statement rules, and table schema existence. |
| **Safety Engine** | `sqlpilot/core/safety_engine.py` | 5-Tier Safety Classifier (`READ`, `DML`, `DDL`, `DESTRUCTIVE`, `UNKNOWN`). |
| **Permission Gate** | `sqlpilot/core/permission_gate.py` | Rich UI prompt card rendering SQL, explanation, risk level, and `[Y]/[N]` confirmation. |
| **Execution Engine** | `sqlpilot/core/execution_engine.py` | Safe SQLite execution in transaction blocks returning tabular rows and latency metrics. |
| **Correction Engine** | `sqlpilot/core/correction_engine.py` | Automatic error traceback analysis and LLM retry loop (max 2 attempts). |
| **History Telemetry** | `sqlpilot/core/history_metrics.py` | SQLite audit logger recording queries, safety levels, approval choices, and timing. |
| **CLI Application** | `sqlpilot/cli.py` | `Typer` + `Rich` interactive REPL terminal interface (`$ sqlpilot`). |
| **Evaluation Harness** | `eval/runner.py` | Benchmark evaluation runner evaluating 11 test cases across 8 query categories. |

---

## 4. Test & Benchmark Results

- **Unit Test Suite**: `18 passed in 0.10s` (`tests/test_schema_inspector.py`, `tests/test_sql_parser.py`, `tests/test_safety_engine.py`, `tests/test_execution_engine.py`, `tests/test_benchmark_runner.py`).
- **Evaluation Benchmark Results**:
  - `total_benchmark_queries`: 11
  - `rag_schema_relevance_accuracy`: **100.0%**
  - `safety_classification_accuracy`: **100.0%**
  - `average_latency_ms`: **0.36 ms**

---

## 5. Development Progress Log

- **2026-08-31**:
  - Created and validated full system implementation for **SQLPilot**.
  - Seeded 5-table SQLite sample database (`data/sample_store.db`).
  - Implemented all core components (`SchemaInspector`, `SchemaRetriever`, `GeminiLLMProvider`, `SQLParserValidator`, `SafetyEngine`, `PermissionGate`, `ExecutionEngine`, `CorrectionEngine`, `HistoryMetricsLogger`).
  - Built Typer + Rich CLI interface (`sqlpilot/cli.py`).
  - Built evaluation benchmark harness (`eval/runner.py`) achieving 100% safety & retrieval accuracy.
  - Achieved complete unit test pass (18/18 passed).
