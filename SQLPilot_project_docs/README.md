# SQLPilot

**Natural Language → Schema Retrieval → SQL → Validation → Safe Execution**

SQLPilot is a local AI-powered database assistant that allows users to interact with relational databases using plain English.

It combines LLM-based SQL generation with deterministic validation and a human-in-the-loop safety layer.

## Why SQLPilot?

Generating SQL with an LLM is easy.

Generating SQL that can be **safely and reliably executed** is the actual engineering problem.

SQLPilot treats generated SQL as untrusted input.

```text
User
 ↓
Natural Language
 ↓
Relevant Schema Retrieval
 ↓
Gemini
 ↓
Generated SQL
 ↓
SQL Parser
 ↓
Validator
 ↓
Safety Classifier
 ↓
Approval when required
 ↓
Database
```

## Key Features

- Natural-language to SQL
- Automatic database schema inspection
- Schema-aware retrieval / RAG
- SQL parsing and validation
- Read/DML/DDL classification
- Human approval for modifications
- Plain-English explanation of SQL impact
- Destructive-operation warnings
- Limited automatic SQL correction
- Query history and execution metrics
- Evaluation benchmark

## Example

User:

```text
Show the top 5 customers by spending this year.
```

SQLPilot generates SQL using the relevant schema and validates it before execution.

For a modification:

```text
Add an email column to customers.
```

SQLPilot stops before execution:

```text
Permission Required

SQL Query:
ALTER TABLE customers
ADD COLUMN email VARCHAR(255);

What this query does:
This modifies the customers table by adding an email column.

Impact:
- The schema will change.
- Existing records will remain.
- Existing rows will have NULL in the new column.

Do you want to execute this query?

[Y] Yes, Execute
[N] No, Cancel
```

## Initial Stack

- Python
- SQLite
- SQLAlchemy
- SQLGlot
- Pydantic
- pytest
- Gemini API
- Typer / Rich

## Project Principle

> The LLM generates a proposal. The application decides whether that proposal is safe to execute.

## Current Scope

The first release targets SQLite and a terminal interface.

A VS Code extension is a future interface built on top of the same core engine.
