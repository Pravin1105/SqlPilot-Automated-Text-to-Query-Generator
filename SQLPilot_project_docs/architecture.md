# SQLPilot — System Architecture

## 1. Architectural Principle

SQLPilot follows a controlled AI execution architecture:

> The LLM proposes SQL; deterministic application components validate, classify, authorize, and execute it.

The LLM must never have direct unrestricted authority over the database.

## 2. High-Level Architecture

```text
                         SQLPilot CLI
                              │
                              ▼
                       Application Core
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   Schema Engine         LLM Engine          SQL Engine
          │                   │                   │
          │                   │            ┌──────┴──────┐
          │                   │            ▼             ▼
          │                   │       Validator       Safety
          │                   │            │             │
          └───────────┬───────┴────────────┴─────────────┘
                      ▼
                 Execution Gate
                      │
             ┌────────┴────────┐
             ▼                 ▼
        Auto-execute       User Approval
        read-only          modification
             │                 │
             └────────┬────────┘
                      ▼
                   Database
```

## 3. Components

### 3.1 CLI Layer

Responsible for:
- starting sessions
- accepting natural-language input
- displaying SQL
- displaying results
- displaying warnings
- collecting approval

The CLI should not contain database or LLM business logic.

### 3.2 Schema Inspector

Reads the database metadata and creates a normalized representation:

```text
Database
 ├── Table
 │    ├── Column
 │    ├── Primary Key
 │    └── Foreign Keys
 └── Relationships
```

### 3.3 Schema Retriever

Given a user request, selects relevant schema objects.

Initial implementation can use deterministic keyword/table matching. Semantic retrieval can be added later.

This component is the project's RAG layer: schema information is retrieved and supplied as context to the LLM.

### 3.4 LLM Provider

Expose a common interface:

```python
class LLMProvider:
    def generate_sql(self, request, schema_context):
        ...
```

Initial provider:
- Gemini API

Future provider:
- local model through an adapter such as Ollama

### 3.5 SQL Generator

Builds the controlled prompt containing:
- user request
- relevant schema
- SQL dialect
- generation rules
- safety requirements

It returns structured data rather than arbitrary text where possible.

### 3.6 SQL Parser

Use SQLGlot or equivalent parsing functionality to understand the generated query.

The parser identifies:
- statement type
- referenced tables
- referenced columns where possible
- potentially destructive operations

### 3.7 SQL Validator

Performs deterministic checks before execution.

The validator should reject:
- malformed SQL
- unsupported statements
- invalid object references
- multiple statements where not supported
- unsafe constructs

### 3.8 Safety Engine

Classifies queries:

```text
READ
DML
DDL
DESTRUCTIVE
UNKNOWN
```

Unknown queries should fail closed rather than execute.

### 3.9 Permission Gate

For non-read operations, the system generates an approval view containing:

```text
SQL Query
What it does
Affected objects
Expected impact
Risk level
Approval request
```

No approval means no execution.

### 3.10 Execution Engine

The execution engine receives only validated and authorized SQL.

It is responsible for:
- executing the query
- collecting results
- measuring execution time
- capturing database errors

### 3.11 Correction Engine

For an execution error:

```text
SQL
 ↓
Database Error
 ↓
Correction Prompt
 ↓
LLM
 ↓
New SQL
 ↓
Validation
```

Maximum correction attempts should be configurable and small, for example 2.

### 3.12 History / Observability

Persist experiment and execution information in SQLite:

```text
requests
generated_queries
executions
errors
approvals
metrics
```

## 4. Security Boundary

The most important boundary is:

```text
LLM
 ↓
UNTRUSTED SQL
 ↓
Parser
 ↓
Validator
 ↓
Safety Classifier
 ↓
Permission Gate
 ↓
Database
```

The generated SQL is treated as untrusted input.

The system should not rely on the LLM saying that a query is safe.

## 5. Failure Handling

If schema retrieval fails:
- report the failure
- do not fabricate schema

If SQL parsing fails:
- do not execute

If validation fails:
- show the reason
- optionally request correction

If execution fails:
- capture the database error
- allow limited correction

If ambiguity is detected:
- request clarification

If safety classification is unknown:
- block execution

## 6. Database Strategy

Initial database:

```text
SQLite
  ↓
sample.db
```

The application should use SQLAlchemy so that additional database backends can be introduced later.

Initial target schema:

```text
customers
orders
products
order_items
payments
```

## 7. Data Flow

```text
User Request
    ↓
Request Parser
    ↓
Schema Retriever
    ↓
Prompt Builder
    ↓
Gemini
    ↓
SQL
    ↓
SQLGlot Parser
    ↓
Validator
    ↓
Safety Classifier
    ↓
Permission Gate if required
    ↓
SQLAlchemy
    ↓
SQLite
    ↓
Result / Error
```

## 8. Design Decisions

### Why SQLite first?
It requires no server setup and makes the project easy to reproduce locally.

### Why SQLGlot?
SQL parsing should be handled by a SQL parser rather than regex-only checks.

### Why separate LLM and safety layers?
LLMs are probabilistic. Security and authorization should be deterministic wherever possible.

### Why schema retrieval?
Large schemas waste context and increase the probability of incorrect table selection. Relevant schema retrieval also provides a natural RAG component.

### Why a provider abstraction?
It prevents the core system from becoming dependent on one model vendor.

## 9. Future Extension

The architecture can later expose an HTTP API:

```text
VS Code Extension
       ↓
FastAPI
       ↓
SQLPilot Core
```

This allows the same core system to support:
- terminal
- VS Code
- web UI
- other database tools
without rewriting the core logic.
