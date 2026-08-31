# SQLPilot — Demo Walkthrough

## 1. Start

```bash
sqlpilot
```

Expected:

```text
SQLPilot
Connected to: sample.db
```

## 2. Read Query

User:

```text
Show the top 5 customers by total spending this year.
```

System:
1. Retrieves relevant schema.
2. Sends request + schema to Gemini.
3. Generates SQL.
4. Parses and validates SQL.
5. Classifies it as READ.
6. Executes it.
7. Displays SQL and results.

## 3. Schema Modification

User:

```text
Add an email column to customers.
```

System generates:

```sql
ALTER TABLE customers
ADD COLUMN email VARCHAR(255);
```

The system must stop and show:

```text
Permission Required

SQL Query:
ALTER TABLE customers
ADD COLUMN email VARCHAR(255);

What this query does:
This modifies the customers table by adding an email column
that can store up to 255 characters.

Impact:
- The database schema will change.
- Existing records will not be deleted.
- Existing rows will receive NULL for this new column.

Do you want to execute this query?

[Y] Yes, Execute
[N] No, Cancel
```

If the user selects `N`, the query must not execute.

If the user selects `Y`, it is executed after the final validation step.

## 4. Destructive Query

User:

```text
Delete all orders.
```

The system should produce a high-risk warning and require explicit approval.

## 5. Invalid SQL

If the LLM produces invalid SQL:

```text
Generated SQL
      ↓
Parser
      ↓
Validation Failure
      ↓
Correction Attempt
      ↓
Validation
```

The system should never execute the original invalid query.

## 6. Ambiguous Request

User:

```text
Show me the best customers.
```

The system should not invent a definition of "best".

It should ask:

```text
What should "best" mean?

1. Highest total spending
2. Most orders
3. Most recent purchases
```

## 7. Demo Message

The central message of the demonstration:

> SQLPilot does not blindly execute what an LLM generates. It treats generated SQL as an untrusted proposal, validates it, explains its impact, and requires human approval for database changes.
