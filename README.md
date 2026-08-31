# SQLPilot — Automated Text-to-Query Generator

> **SQLPilot** is a local, schema-aware AI database assistant that converts plain English questions into valid SQL queries and safely executes them against relational databases using deterministic validation, 5-tier safety classification, human authorization, and controlled execution.

---

## 🌟 Core Philosophy & Security Principle

Generating SQL with an LLM is easy. Generating SQL that can be **safely and reliably executed** against production or development databases is the real software engineering challenge.

> [!IMPORTANT]
> **Execution Boundary Rule**: *The LLM generates a proposed database action. It is NEVER given execution authority.* Every generated query is strictly treated as **untrusted input**.

```text
User Natural Language Request ($ sqlpilot)
                ↓
    Database Schema Inspection (`SchemaInspector`)
                ↓
  Schema RAG Retrieval (`SchemaRetriever` - Relevant subsetting)
                ↓
    Gemini LLM SQL Generation (`GeminiLLMProvider`)
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

## ✨ Key Features

- **Natural Language → SQL**: Translates complex plain English requests into SQLite dialect queries.
- **Automatic Schema Inspection**: Automatically inspects table structures, column data types, primary keys, foreign keys, and constraints using SQLite `PRAGMA`.
- **Schema-Aware RAG Component**: Instead of passing bloated database schemas to the LLM, retrieves *only* tables, columns, and foreign key relationships relevant to the user's question.
- **Deterministic AST Parsing (`SQLGlot`)**: Parses generated queries into Abstract Syntax Trees (AST) to verify syntax, enforce single-statement security rules, and validate table existence against the schema.
- **5-Tier Safety Classifier**:
  - `READ` (`SELECT`): Auto-executes after AST validation.
  - `DML` (`INSERT`, `UPDATE`, `DELETE`): Requires user authorization with impact summary.
  - `DDL` (`CREATE`, `ALTER`): Requires user authorization with schema change warning.
  - `DESTRUCTIVE` (`DROP TABLE`, `TRUNCATE`, unrestricted `DELETE`): Displays high-visibility safety warning cards requiring explicit confirmation.
  - `UNKNOWN`: Automatically blocked (fails closed).
- **Human-in-the-Loop Authorization Gate**: Solicits explicit user consent (`[Y]/[N]`) for modifications, presenting the query, plain-English explanation, and schema impact breakdown.
- **Dynamic Multi-Database Switching (v1.2)**:
  - Command: `connect <database_name.db>`
  - Command: `disconnect <database_name.db>`
  - Enforces strict two-step switching (`disconnect` before `connect`), checks file existence, and validates exact database matching.
- **Database Self-Correction Retry Loop**: On runtime execution errors (e.g. type mismatch), captures database tracebacks and feeds context back to the LLM for automatic fix generation (max 2 retries).
- **Observability & History Telemetry**: Records audit logs of questions, generated queries, safety levels, user approval decisions, row counts, and execution latency to an SQLite telemetry store (`data/history.db`).
- **Benchmark Evaluation Suite**: Evaluates pipeline performance across benchmark datasets (`eval/runner.py`) measuring retrieval relevance, safety accuracy, and execution success.
- **CI/CD Pipeline**: GitHub Actions workflow testing Python 3.9, 3.10, and 3.11 compatibility.

---

## 🛠️ Technology Stack

- **Language**: Python 3.11+ (Clean, idiomatic, fully type-hinted)
- **Database Engine**: SQLite (Embedded, zero setup)
- **ORM & Introspection**: SQLAlchemy / SQLite `PRAGMA`
- **SQL Parser**: SQLGlot (AST parsing)
- **Data Contracts**: Pydantic v2 / Dataclasses
- **LLM Integration**: Google Gemini API (`google-genai` SDK, `gemini-3.6-flash` default)
- **CLI & UI**: Typer + Rich
- **Testing & Benchmarking**: Pytest + Custom Evaluation Runner
- **CI/CD**: GitHub Actions

---

## 📂 Project Architecture

```text
QueryGenerator/
├── README.md
├── CONTEXT.md
├── memory.md                          # Living project decision log
├── pyproject.toml / setup.py          # Package specifications
├── config.py                          # Pydantic Settings
├── data/
│   ├── sample_store.db                # Sample E-Commerce Database (5 tables)
│   └── sample_hr.db                   # Sample HR Database (3 tables)
├── sqlpilot/
│   ├── __init__.py
│   ├── cli.py                         # Typer + Rich Interactive REPL Interface
│   ├── core/
│   │   ├── __init__.py
│   │   ├── connection_manager.py      # Multi-db connection & switch manager
│   │   ├── schema_inspector.py        # Table/Column/PK/FK metadata discovery
│   │   ├── schema_rag.py              # Contextual schema subset retriever
│   │   ├── llm_provider.py            # Gemini LLM provider abstraction
│   │   ├── sql_generator.py           # NL to SQL prompt & response generator
│   │   ├── sql_parser.py              # SQLGlot AST parser & reference validator
│   │   ├── safety_engine.py           # 5-tier query safety classifier
│   │   ├── permission_gate.py         # Rich UI human approval gate
│   │   ├── execution_engine.py        # Safe SQLite execution engine
│   │   ├── correction_engine.py       # DB traceback error self-correction loop
│   │   └── history_metrics.py         # Telemetry & query history logger
│   └── db/
│       ├── __init__.py
│       ├── sample_db_builder.py       # E-Commerce DB seeder
│       └── sample_hr_db_builder.py    # HR DB seeder
├── eval/
│   ├── benchmark_queries.json         # Evaluation test suite (11 test prompts)
│   └── runner.py                      # Benchmark evaluator & reporting harness
├── tests/
│   ├── test_schema_inspector.py
│   ├── test_sql_parser.py
│   ├── test_safety_engine.py
│   ├── test_execution_engine.py
│   ├── test_multi_db_connection.py
│   └── test_benchmark_runner.py
└── .github/
    └── workflows/
        └── ci.yml                     # GitHub Actions CI/CD Pipeline
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.9 or higher
- Google Gemini API Key

### 2. Installation

Clone the repository and set up a Python virtual environment:

```bash
git clone https://github.com/Pravin1105/SqlPilot-Automated-Text-to-Query-Generator.git
cd SqlPilot-Automated-Text-to-Query-Generator

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies and package in editable mode
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install --no-build-isolation -e .
```

### 3. Set Gemini API Key

```bash
export GEMINI_API_KEY="your_gemini_api_key_here"

# (Optional) Override default Gemini model
export GEMINI_MODEL="gemini-3.6-flash"
```

---

## 💻 CLI Usage & Commands

Launch the interactive SQLPilot terminal:

```bash
sqlpilot
```

### Interactive REPL Commands

| Command | Action | Example |
| :--- | :--- | :--- |
| `connect <database_name.db>` | Connects to a target database file in `data/`. Verifies file existence. | `connect sample_hr.db` |
| `disconnect <database_name.db>` | Disconnects active session. Verifies database name match strictly. | `disconnect sample_store.db` |
| `<natural language question>` | Translates question into SQL, validates AST, requests approval if modifying, and executes. | `Show top 5 customers by spending this year.` |
| `exit` / `quit` | Closes SQLPilot CLI session. | `exit` |

---

## 💡 Example Walkthrough

### 1. Read Query (Auto-Executed)
```text
sqlpilot(sample_store.db)> Show top 5 customers by spending this year.

Generated SQL:
SELECT c.customer_id, c.first_name, c.last_name, SUM(o.total_amount) AS total_spending
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id
ORDER BY total_spending DESC
LIMIT 5;

Explanation: Calculates total spending per customer by joining customers and orders.
Query Executed Successfully (1.24 ms)
```

### 2. Two-Step Database Switching (v1.2 Rule)
```text
# Attempting direct connect while connected is blocked
sqlpilot(sample_store.db)> connect sample_hr.db
-> Error: Already connected to 'sample_store.db'. You must run 'disconnect sample_store.db' before connecting to another database.

# Step 1: Disconnect
sqlpilot(sample_store.db)> disconnect sample_store.db
-> Successfully disconnected from 'sample_store.db'.

# Step 2: Connect to new database
sqlpilot(disconnected)> connect sample_hr.db
-> Successfully connected to 'sample_hr.db'. Schema indexed.

# Query new database!
sqlpilot(sample_hr.db)> List all employees in Engineering department.
```

### 3. Schema Modification (Human Approval Gate)
```text
sqlpilot(sample_store.db)> Add an email column to customers.

⚠️ PERMISSION REQUIRED FOR DATABASE MODIFICATION
SQL Query:
ALTER TABLE customers ADD COLUMN email VARCHAR(255);

What this query does:
Modifies the customers table by adding an email column.

Impact Assessment:
  • The database schema structure will change.
  • Affected table(s): customers

Do you want to execute this query? [y/N]:
```

---

## 🧪 Testing & Evaluation

### Run Pytest Unit Tests (25 Tests)

```bash
PYTHONPATH=. pytest tests/ --verbose
```

### Run Evaluation Benchmark Suite

```bash
PYTHONPATH=. python eval/runner.py
```

Benchmark Output:
```json
{
  "total_benchmark_queries": 11,
  "rag_schema_relevance_accuracy": 100.0,
  "safety_classification_accuracy": 100.0,
  "total_benchmark_duration_s": 0.003,
  "average_latency_ms": 0.23
}
```

---

## 📄 Documentation Index

- [memory.md](file:///Users/pravin/Documents/QueryGenerator/memory.md) — Living project decision log and progress state.
- [CONTEXT.md](file:///Users/pravin/Documents/QueryGenerator/CONTEXT.md) — Detailed requirements and architecture specifications.
- [SQLPilot_project_docs/](file:///Users/pravin/Documents/QueryGenerator/SQLPilot_project_docs/) — Subdirectory containing PRD, Security Model, and Architecture docs.

---

## 📜 License

MIT License — free for educational, research, and commercial use.
