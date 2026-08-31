# SQLPilot — Evaluation Plan

## Objective

Measure whether SQLPilot converts natural-language requests into correct and safely executable SQL.

## Dataset

Create a fixed benchmark of 50–100 natural-language requests.

Each case should contain:

```json
{
  "id": "Q001",
  "question": "Which customers spent the most this year?",
  "expected_sql": "...",
  "expected_result": "...",
  "category": "aggregation"
}
```

## Test Categories

- simple SELECT
- filtering
- sorting
- aggregation
- GROUP BY
- joins
- date filtering
- nested queries
- ambiguous requests
- invalid requests
- INSERT
- UPDATE
- DELETE
- CREATE
- ALTER
- DROP
- TRUNCATE

## Metrics

### SQL Correctness

Does the generated SQL represent the requested operation?

### Execution Success

Does the query execute successfully against the target database?

### Result Correctness

Does it return the expected information?

### Safety Accuracy

Does the system correctly classify read-only, modifying, and destructive queries?

### Approval Coverage

Are all queries requiring user authorization stopped before execution?

### Correction Success

When SQL fails, how often does the correction engine produce a valid query?

### Latency

Measure:
- schema retrieval time
- LLM latency
- validation time
- database execution time
- total request time

### Token Usage

Record input/output token usage when the provider exposes it.

## Regression Testing

Every major prompt or model change should be evaluated against the same benchmark.

A new version should not be accepted merely because its average score improves if it introduces critical safety regressions.

Example:

```text
Version       SQL Accuracy    Safety Errors

v1            87%             0
v2            92%             0
v3            94%             2  ← reject
```

A safety regression is more important than a small accuracy improvement.

## Evaluation Goal

The project should demonstrate measurable improvement and reliability rather than relying on a few successful demo queries.
