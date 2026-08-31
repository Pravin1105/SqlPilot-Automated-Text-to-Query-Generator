# SQLPilot — Product Requirements Document

## 1. Project Overview

SQLPilot is a local AI-powered database assistant that converts plain-English requests into SQL, validates the generated query, explains its impact, and safely executes it against a relational database.

The goal is not simply to generate SQL with an LLM. The system should demonstrate how an LLM can be placed inside a controlled software pipeline with schema-aware retrieval, validation, safety checks, human approval, error correction, and measurable evaluation.

## 2. Problem

Writing SQL requires knowledge of database schemas, joins, filtering, aggregation, and SQL syntax. Non-SQL users may know what information they want but not how to express it as a query.

LLM-generated SQL introduces another problem: a generated query can be syntactically wrong, reference the wrong schema, return incorrect results, or modify/delete data.

SQLPilot addresses both problems by separating:
- LLM-based language understanding and SQL generation
- deterministic schema inspection and SQL validation
- safety classification
- human authorization
- database execution

## 3. Target Users

- Developers working with relational databases
- Students learning SQL and databases
- Analysts who understand business questions better than SQL syntax
- Engineers experimenting with LLM-based database interfaces

## 4. Goals

1. Convert natural-language requests into executable SQL.
2. Automatically understand the connected database schema.
3. Retrieve relevant schema information before generation.
4. Validate generated SQL before execution.
5. Detect read, data-modification, and schema-modification queries.
6. Require explicit approval for queries that change data or schema.
7. Explain generated SQL in plain English.
8. Attempt limited automatic correction when SQL execution fails.
9. Record queries, outcomes, errors, and performance metrics.
10. Provide an evaluation benchmark for measuring system quality.

## 5. Non-Goals

- Building a complete database management system
- Replacing native SQL clients
- Supporting every SQL dialect in the first release
- Training a foundation model
- Building a general-purpose chatbot
- Automatically executing destructive operations without user approval

## 6. Core Workflow

```text
Natural Language Request
        ↓
Schema Inspection / Retrieval
        ↓
LLM SQL Generation
        ↓
SQL Parsing & Validation
        ↓
Safety Classification
        ↓
 ┌───────────────┬──────────────────┐
 │ Read-only     │ Modification     │
 │               │                  │
 ↓               ↓                  │
Execute      Explain + Ask User     │
                ↓                   │
          Approve / Reject          │
                ↓                   │
             Execute                │
```

## 7. Functional Requirements

### FR-01: Database Connection
The system shall connect to a local SQLite database for the initial implementation.

### FR-02: Schema Inspection
The system shall identify tables, columns, data types, primary keys, foreign keys, and relationships.

### FR-03: Schema Retrieval
The system shall identify schema information relevant to the user's request instead of unnecessarily sending the complete schema to the LLM.

### FR-04: SQL Generation
The system shall use an LLM to generate SQL from the user's natural-language request and relevant schema context.

### FR-05: SQL Validation
Every generated query shall pass through a validation layer before execution.

Validation should include:
- SQL syntax
- referenced tables
- referenced columns where practical
- supported SQL operations
- database compatibility
- malformed or suspicious statements

### FR-06: Query Classification
Queries shall be classified as:
- READ: SELECT and equivalent read-only operations
- DML: INSERT, UPDATE, DELETE
- DDL: CREATE, ALTER, DROP, TRUNCATE

### FR-07: Human Approval
DML and DDL queries shall not execute automatically.

The system shall show:
1. The generated SQL query
2. A plain-English description of what it does
3. The affected table/object where identifiable
4. The expected impact
5. A clear request for permission

Example:

```text
Permission Required

SQL Query:
ALTER TABLE customers ADD COLUMN email VARCHAR(255);

What this query does:
This modifies the customers table by adding an email column
that can store up to 255 characters.

Impact:
- The database schema will change.
- Existing rows will not be deleted.
- Existing rows will have NULL in the new column.

Do you want to execute this query?

[Y] Yes, Execute
[N] No, Cancel
```

### FR-08: Destructive Operation Warning
Operations such as DROP and TRUNCATE shall receive stronger warnings and shall clearly state that data or database objects may be permanently removed.

### FR-09: Query Execution
Only validated queries may reach the database execution layer.

### FR-10: Error Correction
When execution fails, the system may provide the database error to the LLM and request a corrected query. Correction attempts shall be limited.

### FR-11: Ambiguity Detection
The system should identify requests that cannot be safely mapped to a unique interpretation and ask the user to clarify.

### FR-12: Explanation
The system shall show generated SQL and provide a concise plain-English explanation.

### FR-13: History
The system should record:
- user request
- generated SQL
- classification
- execution status
- error information
- execution time
- correction attempts

## 8. Evaluation Requirements

The project shall include a fixed benchmark containing natural-language questions and expected SQL/results.

Metrics should include:
- SQL generation correctness
- execution success rate
- result correctness
- schema retrieval relevance
- correction success rate
- average latency
- token usage where available

## 9. Initial Technology

- Python
- SQLite
- SQLAlchemy
- SQLGlot
- Pydantic
- pytest
- Gemini API through a provider abstraction
- Typer/Rich for the CLI

The architecture should allow a local LLM provider to be added later without changing the core application.

## 10. MVP Definition

The MVP is complete when a user can:

```text
Start SQLPilot
    ↓
Connect to sample.db
    ↓
Ask an English question
    ↓
Receive generated SQL
    ↓
See validation result
    ↓
Automatically execute read-only queries
    ↓
Receive an English explanation + approval prompt for modifications
    ↓
Execute approved modifications
```
