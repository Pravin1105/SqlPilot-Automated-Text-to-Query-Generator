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

- [CONTEXT.md](CONTEXT.md) — Comprehensive technical architecture, phased roadmap, and security model.

---

## 🌟 What's New in Version 2.0 (v2.0)

SQLPilot v2.0 elevates the project from a CLI prototype into a production-ready, security-hardened **Web Workspace** designed for real-world deployments with complete data privacy, client-side isolation, and an interactive interface.

### 🔑 Key Changes in v2.0

1. **Zero-Dependency Modern Web Workspace**:
   - High-performance, minimalist desktop database console built with standard web technologies (HTML5, CSS3, vanilla ES6 JavaScript) and Python's standard `http.server` backend.
   - Adheres strictly to an ergonomic dark emerald palette (`#092328`, `#12544F`, `#2A835F`, `#8BBB92`). Zero third-party frontend frameworks, zero CDN dependencies, zero external tracking.

2. **Interactive Schema Explorer (Dynamic Push-Down Accordion)**:
   - Left sidebar schema viewer displaying all tables and attributes in the connected database.
   - **Smooth push-down accordion**: Clicking any table row smoothly expands its columns while automatically shifting subsequent rows downward with dynamic, responsive height adaptation.
   - **Semantic tag badges**:
     - `PK` **Primary Key** (distinct emerald accent)
     - `UNIQUE` **Unique Constraint** (light teal outline)
     - `NOT NULL` **Not-Null Constraint** (deep teal badge)
     - `FK ➔ [table]` **Foreign Key** (compact pill with full target metadata in hover tooltip)
   - Real-time search filter for both table names and column names.

3. **Production BYOK (Bring Your Own Key)**:
   - Zero hardcoded API keys: Users configure their own Groq Cloud (`openai/gpt-oss-120b`, `llama-3.3-70b-versatile`) or Google Gemini API key directly through the in-browser **Settings (⚙️)** modal.
   - API keys are stored strictly in client-side browser `localStorage` and passed per-request via secure `X-LLM-Api-Key` HTTP headers. Keys are never saved in database files, session cookies, or server configuration.

4. **Custom Database Upload & Tenant Isolation**:
   - Users can securely upload and connect their own `.db` or `.sqlite` files directly through the **Upload DB (📁)** modal.
   - Security validation: Enforces SQLite 3 binary magic header checking (`SQLite format 3\x00`), filename sanitization, and tenant-isolated storage (`data/user_databases/<username>/`) with POSIX `0600` permissions.
   - Starter database `data/sample_store.db` is bundled for trying out queries immediately.

5. **Offline Zero-Record Privacy Invariant**:
   - Database schema extraction, vector chunking, and TF-IDF RAG retrieval execute **100% offline** on the user's local machine.
   - **Zero rows, records, or tuples are EVER read, embedded, or transmitted to any external LLM.** Only structural DDL schema metadata (table names, column names, constraints) is shared with the model.

6. **Human-in-the-Loop Safety Gate**:
   - Safe `READ` (`SELECT`) queries execute autonomously against the local database and render data tables with execution metrics.
   - Any modifying operations (`INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`) halt at the **Permission Gate**, presenting the generated SQL, plain-English explanation, and schema impact assessment for explicit user confirmation.

7. **Multi-User Authentication**:
   - Salted PBKDF2 password hashing with SHA-256 and cryptographically random session tokens for workspace isolation.

---

## 📦 Step-by-Step Guide: Running SQLPilot from Clone

Follow these steps to run SQLPilot locally on your machine from scratch:

### Step 1: Clone the Repository

```bash
git clone https://github.com/Pravin1105/SqlPilot-Automated-Text-to-Query-Generator.git
cd SqlPilot-Automated-Text-to-Query-Generator
```

### Step 2: Create and Activate a Virtual Environment

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows (Command Prompt)
python -m venv .venv
.venv\Scripts\activate.bat

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Launch the Web Workspace

Start the local server daemon:

```bash
python3 sqlpilot/web/server.py --port 8000
```

You will see:
```text
==================================================
 SQLPilot Web Workspace (Phase 3 Active)
 Connected DB: sample_store.db
 Auth Enforced: True
 Serving directory: .../sqlpilot/web/static
==================================================
```

### Step 5: Open in Your Browser & Log In

1. Open **[http://localhost:8000](http://localhost:8000)** in Chrome, Safari, Firefox, or Edge.
2. Log in using the default administrator credentials:
   - **Username**: `admin`
   - **Password**: `admin`

### Step 6: Configure Your LLM API Key (BYOK)

1. Click the **API Key (⚙️)** button in the top navigation bar.
2. Select your provider:
   - **Groq Cloud (Recommended)**: Paste your Groq API key (`gsk_...`) and choose your model (e.g., `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`).
   - **OpenAI**: Paste your OpenAI API key (`sk-proj-...` or `sk-...`) and choose your model (e.g., `gpt-4o-mini`, `gpt-4o`, `o3-mini`).
   - **Anthropic Claude**: Paste your Claude API key (`sk-ant-...`) and choose your model (e.g., `claude-3-5-haiku-20241022` or `claude-3-7-sonnet-20250219`).
   - **Google Gemini**: Paste your Gemini API key (`AIza...`) and choose your model (e.g., `gemini-2.0-flash` or `gemini-1.5-pro`).
3. Click **Save Settings**. Your key is securely stored in your local browser storage.

### Step 7: Start Querying & Connect Your Own Database!

- **Query the Starter Store**: Try one of the example chips or ask a question:
  ```text
  show me the top 5 customers by total spending this year
  ```
- **Upload Your Own Database**: Click **Upload DB (📁)**, select your `.sqlite` or `.db` file, and explore its tables and columns in the interactive Schema Explorer!

---

### Alternative: CLI Mode

You can also run SQLPilot directly in your terminal:

```bash
python3 sqlpilot/cli.py interactive
```

---

### 🌐 Deploying to Vercel

SQLPilot is 100% production-ready for zero-config deployment on Vercel:

1. **Import your GitHub repository** at [vercel.com/new](https://vercel.com/new).
2. Vercel automatically detects `vercel.json` and configures the Python serverless runtime and static CDN routes.
3. *(Optional)* Add default API keys in Vercel **Environment Variables** (`GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`). Users can also enter their own keys directly in the web UI.
4. Click **Deploy**. Your SQLPilot workspace will be live globally!

---

### Running the Test Suite

Run the full automated test suite (74 passing unit and integration tests):

```bash
pytest tests/ --verbose
```

---

## 📜 License

MIT License — free for educational, research, and commercial use.
