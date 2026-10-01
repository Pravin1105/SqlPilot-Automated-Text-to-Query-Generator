# SQLPilot — Project Context & System Specification

**SQLPilot** is a local, schema-aware, AI-assisted database interface that converts natural language requests into SQL and safely executes them against a relational database using deterministic validation, safety classification, human authorization, and controlled execution.

The next version adds a focused, minimal web-based GUI workspace that acts as a secure abstraction layer over locally stored databases.

---

## Codebase Principles: Senior Developer Standard

> [!IMPORTANT]
> **Minimalism, Simplicity & Elegance**:
> - **Zero Bloat / Over-Engineering**: Clean, readable Python with zero enterprise fluff or unnecessary design pattern noise.
> - **Self-Documenting & Typed**: Fully type-hinted, explicit data structures (`dataclasses` / `Pydantic`), concise docstrings.
> - **Auditability**: Every stage of the pipeline (`schema` -> `rag` -> `llm` -> `parser` -> `safety` -> `gate` -> `execution`) is isolated in a small, single-responsibility module that a senior engineer can review in minutes.
> - **Strict Sequential Progression**: Development advances through distinct gated phases. No phase proceeds until its implementation and testing pass senior review.

---

## Architecture & Security Principles

> [!IMPORTANT]
> **Core Security Principles**:
> 1. **Untrusted Input**: The LLM generates a proposed database action. It is NEVER given execution authority. Every query is treated as untrusted input.
> 2. **Backend Authoritative**: The backend makes all security, parsing, validation, and safety decisions. The frontend never determines query safety.
> 3. **Zero Record Leakage**: The database and its records remain local/offline. The LLM will **never receive database tuples or actual records**; only structural schema metadata (tables, columns, types, constraints) is processed.
> 4. **Approval Integrity**: Approval is valid only for the exact SQL statement shown to the user.

### Execution Control Flow

```text
User's Plain-English Request
        ↓
Database Schema Inspection (PRAGMA metadata only)
        ↓
Relevant Schema Retrieval (Local RAG)
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

1. **Schema Engine & Local RAG Retrieval**
   - Automatically inspects tables, columns, data types, primary keys, foreign keys, and relationships.
   - Operates exclusively on structural metadata (zero row data accessed).
   - Locates, chunks, embeds, and retrieves only relevant schema components for a user query.

2. **LLM Provider Abstraction**
   - Clean provider interface for Gemini API (expandable to Ollama / local models).
   - Structured JSON output generation for SQL, explanation, and ambiguity detection.

3. **SQL Parsing & Validation (`sqlglot`)**
   - Deterministic AST parsing (verifying syntax, table references, column validity, multi-statement blocking).

4. **Safety Classifier & Human-in-the-Loop Gate**
   - Classifies queries into `READ`, `DML`, `DDL`, `DESTRUCTIVE`, `UNKNOWN`.
   - `READ`: Auto-executes after passing validation.
   - `DML` / `DDL`: Prompts user with structured impact assessment (`[Yes, Execute]` / `[No, Cancel]`).
   - `DESTRUCTIVE` (`DROP`, `TRUNCATE`, unrestricted `DELETE`/`UPDATE`): Displays high-visibility warning alert before asking for explicit confirmation.
   - `UNKNOWN` / Failed validation: Automatically blocked.

5. **Self-Correction Retry Loop**
   - Captures database runtime errors, feeds tracebacks back to Gemini, and re-routes generated fixes back through the full validation, safety, and authorization pipeline (max N attempts).

6. **Ambiguity Resolution Engine**
   - Detects underspecified or multi-interpretative requests and prompts the user with explicit choices rather than guessing.

7. **History & Telemetry Logger**
   - Persists query execution audit logs, safety levels, approval decisions, row counts, and latency to SQLite storage.

8. **Web Workspace Layer (`sqlpilot.web`)**
   - Minimalist desktop database console and secure abstraction layer.
   - Built with standard web technologies (HTML5, CSS3, vanilla ES6 JS) and zero third-party frontend dependencies.

---

## SQLPilot Web Workspace — Design Specification

### Visual Identity & Color Palette
The interface is a focused database workspace (not a generic SaaS dashboard) adhering to a strict 4-color palette:

| Purpose | Hex Code | Usage |
|---|---|---|
| **Primary dark background** | `#092328` | Main canvas and base background |
| **Secondary surface / panel** | `#12544F` | Sidebar cards, query containers, panels |
| **Accent / active state** | `#2A835F` | Primary buttons, active stepper, PK badges |
| **Light text / highlight** | `#8BBB92` | Section titles, brand highlights, status dots |

### Layout & Interaction Model
- **Header**: SQLPilot identity, active database badge (`sample_store.db`, offline state), and text-first system status indicator.
- **Sidebar**:
  - Connected database indicator and connection status.
  - Interactive Schema Explorer: Collapsible table tree showing columns, data types, `PK` and `FK` badges, and real-time search/filtering.
  - Recent queries list and "New Query" action.
- **Query Console**:
  - Multi-line natural-language prompt textarea (`Enter` to submit, `Shift+Enter` for newline).
  - Sample prompt chips (`READ`, `FILTER`, `DML`, `DESTRUCTIVE`, `ERROR`).
  - Progress stepper: `1. Request` → `2. Schema Retrieval & SQL` → `3. SQLGlot Validation` → `4. Safety Gate` → `5. Database Execution`.
- **Generated SQL Panel**:
  - Monospace SQL code box with copy-to-clipboard functionality.
  - Plain-English explanation box.
  - Safety classification badge (`READ`, `DML`, `DDL`, `DESTRUCTIVE`).
  - **Human-in-the-Loop Approval Gate Banner**:
    - High-visibility warning alert with impact assessment bullet points.
    - Explicit `[Yes, Execute]` and `[No, Cancel]` buttons for modifying queries.
- **Results Panel**:
  - Tabular data presentation with row counts, execution time metrics, and horizontal scrolling.
  - Clean empty, loading, and actionable error states (without raw stack traces).
- **Zero External Calls**: Zero CDNs, zero external fonts, zero third-party UI frameworks.

---

## Phased Development Roadmap

The project follows a strict sequential development gate model:

### Phase 1 — UI / Frontend (COMPLETED ✅)
- **Scope**: Application shell, workspace sidebar, schema explorer, query console, generated SQL panel, results table, human approval gate, loading/empty/error states.
- **Dependencies**: Pure HTML5, CSS3, vanilla JS; Python standard library `http.server` ([server.py](file:///Users/pravin/Downloads/SqlPilot-Automated-Text-to-Query-Generator-main/sqlpilot/web/server.py)).
- **Verification**: `tests/test_phase1_web.py` passes 100% (6/6 tests passing).

### Phase 2 — Connect Existing SQLPilot (COMPLETED ✅)
- **Scope**: Connect web UI to existing SQLPilot core (`ConnectionManager`, `SQLGenerator`, `SQLParserValidator`, `SafetyEngine`, `ExecutionEngine`, `HistoryMetricsLogger`).
- **Endpoints**: `/api/status`, `/api/schema`, `/api/query/generate`, `/api/query/approve`, `/api/query/reject`.
- **Implementation**: Authoritative backend service in [api.py](file:///Users/pravin/Downloads/SqlPilot-Automated-Text-to-Query-Generator-main/sqlpilot/web/api.py), live HTTP routing in [server.py](file:///Users/pravin/Downloads/SqlPilot-Automated-Text-to-Query-Generator-main/sqlpilot/web/server.py), and client integration in [app.js](file:///Users/pravin/Downloads/SqlPilot-Automated-Text-to-Query-Generator-main/sqlpilot/web/static/app.js).
- **Verification**: `tests/test_phase2_web.py` passes 100% (9/9 tests passing); all 40 system regression tests passing (100%).

### Phase 3 — New Architecture & Security Features (COMPLETED ✅)
- **Scope**:
  - Local schema chunking, embedding, and vector retrieval (RAG) with pure Python TF-IDF and n-gram cosine similarity (`sqlpilot/core/schema_embedder.py`).
  - Explicit enforcement of the database-record privacy invariant (zero tuples sent to LLM or vector embeddings).
  - User ID and password authentication for web access with salted PBKDF2 hashing and session tokens (`sqlpilot/web/auth.py`).
  - Multi-database authorization and authorized switching (`/api/databases`, `/api/database/switch`).
  - Web UI integration: Login modal, database switcher, user badge, privacy status indicator.
- **Verification**: `tests/test_phase3_security_rag.py` passes 100% (11/11 tests passing); full project pytest regression suite passes 100% (52/52 tests passing).

### Phase 4 — Production Readiness & BYOK Deployment (COMPLETED ✅)
- **Scope**:
  - **Bring-Your-Own-Key (BYOK)**: End users provide their own Groq Cloud or Google Gemini API keys and select models directly via the GUI Settings modal (⚙️). Keys are stored locally in the browser (`localStorage`) and dynamically injected via `X-LLM-Api-Key` headers per request.
  - **Custom Database Upload & Tenant Isolation**: End users connect their own `.db` / `.sqlite` files with binary magic header validation (`SQLite format 3\x00`), filename sanitization, isolated tenant storage (`data/user_databases/<username>/`), and POSIX `0600` permissions.
  - **Offline Zero-Record Privacy Invariant**: Schema extraction, TF-IDF vector embeddings, and RAG retrieval execute entirely offline on local devices using only SQLite `PRAGMA` DDL metadata. Zero records, tuples, or cells ever reach embeddings or LLM prompts.
  - **Controlled Autonomous Execution**: Safe `READ` (`SELECT`) queries auto-execute on the user's database; modifying operations (`INSERT`, `UPDATE`, `DELETE`, `DDL`, `DESTRUCTIVE`) halt at the human-in-the-loop permission gate with plain-English explanation and impact assessment.
- **Verification**: `tests/test_production_custom_db_and_keys.py` passes 100% (11/11 tests passing); full 63-test system regression suite passes 100% (63/63 tests passing).

---

## Tech Stack

- **Language**: Python 3.9+ / 3.11+ (clean, idiomatic, fully type-hinted)
- **Database Engine**: SQLite (embedded, local)
- **ORM / Introspection**: SQLite PRAGMA / SQLAlchemy
- **SQL Parsing & AST**: SQLGlot
- **Data Validation & Settings**: Pydantic v2
- **LLM Integration**: Google Gemini API (via clean LLM Provider abstraction)
- **CLI Interface**: Typer + Rich
- **Web Interface**: Standard HTML5, CSS3, ES6 JavaScript, Python HTTP / API server
- **Testing**: Python unittest / Pytest + custom benchmark runner
