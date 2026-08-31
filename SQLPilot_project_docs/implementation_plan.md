# SQLPilot — Implementation Plan

## Phase 0 — Project Setup

Create:

```text
SQLPilot/
├── app/
├── database/
├── prompts/
├── tests/
└── docs/
```

Set up Python environment, dependencies, configuration, and Git.

## Phase 1 — SQLite Database

Create a realistic sample database containing:

- customers
- products
- orders
- order_items
- payments

Populate enough data to test joins, aggregation, filtering, sorting, dates, and modifications.

**Deliverable:** `database/sample.db`

## Phase 2 — Schema Inspector

Implement:
- table discovery
- column discovery
- data types
- primary keys
- foreign keys
- relationship extraction

**Deliverable:** a structured schema object.

## Phase 3 — Basic CLI

Implement:

```text
sqlpilot
>
```

Support:
- natural-language input
- exit command
- database connection status

## Phase 4 — Gemini Integration

Implement a provider interface and Gemini provider.

Generate SQL using:
- user request
- database dialect
- relevant schema
- strict SQL-generation instructions

Do not implement automatic execution yet.

## Phase 5 — SQL Parser and Validator

Add SQLGlot.

Implement:
- syntax parsing
- statement classification
- table/reference checks
- multiple-statement blocking
- unsupported operation detection

## Phase 6 — Safety Layer

Implement:

```text
READ
DML
DDL
DESTRUCTIVE
UNKNOWN
```

Unknown must be blocked.

## Phase 7 — Human Approval

Build the English safety message.

Every modification must show:

1. SQL
2. What the SQL does
3. Expected impact
4. Risk
5. Approval choice

Only explicit approval can continue execution.

## Phase 8 — Execution

Implement read-only execution first.

Then enable approved DML/DDL execution.

Record:
- execution status
- duration
- affected rows where available
- errors

## Phase 9 — Error Correction

Add limited LLM-based correction.

The correction prompt should contain:
- original request
- relevant schema
- failed SQL
- database error

The corrected query must return to the normal validation/safety pipeline.

## Phase 10 — Schema Retrieval / RAG

Start with deterministic retrieval.

Then optionally add semantic retrieval for larger schemas.

Measure whether retrieval improves SQL generation.

## Phase 11 — Evaluation

Create a benchmark of approximately 50–100 test cases.

Categories:
- simple lookup
- filtering
- aggregation
- joins
- date queries
- ambiguous requests
- invalid requests
- DML
- DDL
- destructive operations

Measure:
- SQL correctness
- execution success
- result correctness
- correction success
- latency
- token usage

## Phase 12 — Polish

Add:
- Rich CLI output
- configuration file
- logging
- clear errors
- README
- architecture diagrams
- demo script
- tests

## Phase 13 — Optional VS Code Extension

Only after the core system is stable.

Expose the core through FastAPI and build a thin VS Code client.

The extension should not contain the core database/LLM logic.
