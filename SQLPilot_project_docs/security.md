# SQLPilot — Security and Safety Model

## Core Rule

Generated SQL is untrusted.

The LLM must never receive unrestricted execution authority.

## Query Classification

```text
READ
DML
DDL
DESTRUCTIVE
UNKNOWN
```

### READ

Examples:
- SELECT

May execute automatically after validation.

### DML

Examples:
- INSERT
- UPDATE
- DELETE

Requires explicit user approval.

### DDL

Examples:
- CREATE
- ALTER
- DROP
- TRUNCATE

Requires explicit user approval.

### DESTRUCTIVE

Examples:
- DROP TABLE
- DROP DATABASE where supported
- TRUNCATE
- broad DELETE/UPDATE without restrictive conditions

Requires a stronger warning.

### UNKNOWN

If classification is uncertain, execution is blocked.

## Approval Message

The approval message must always include:

1. SQL query
2. Plain-English description
3. Expected impact
4. Affected object(s), where identifiable
5. Explicit approval choice

## Important Safety Behaviors

- Never execute unvalidated SQL.
- Never trust an LLM-generated safety classification.
- Prefer parser-based classification.
- Block multiple statements unless explicitly supported.
- Do not silently rewrite destructive queries.
- Do not execute after a rejected approval.
- Limit automatic correction attempts.
- Keep database credentials outside source code.
- Do not commit API keys or secrets.

## Future Hardening

For production-like operation, add:
- database user permissions
- transaction rollback
- query timeout
- row limits
- resource limits
- audit logging
- allow/deny policies
- read-only database credentials for normal use
