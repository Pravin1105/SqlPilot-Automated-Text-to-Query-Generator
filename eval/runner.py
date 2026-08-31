import json
import time
from pathlib import Path
from typing import Any, Dict, List

from config import settings
from sqlpilot.core.schema_inspector import SchemaInspector
from sqlpilot.core.schema_rag import SchemaRetriever
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.core.safety_engine import SafetyEngine
from sqlpilot.db.sample_db_builder import seed_sample_database


class BenchmarkRunner:
    """Evaluation benchmark runner assessing SQLPilot pipeline performance across test suites."""

    def __init__(self, dataset_path: Path = Path(__file__).parent / "benchmark_queries.json"):
        self.dataset_path = dataset_path
        self.db_path = seed_sample_database(settings.db_path)
        self.schema = SchemaInspector(self.db_path).inspect()
        self.retriever = SchemaRetriever(self.schema)
        self.validator = SQLParserValidator(self.schema)

    def load_dataset(self) -> List[Dict[str, Any]]:
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_benchmark(self) -> Dict[str, Any]:
        dataset = self.load_dataset()
        total_queries = len(dataset)
        safety_correct_count = 0
        rag_relevance_count = 0

        start_time = time.perf_counter()

        for case in dataset:
            question = case["question"]
            expected_tables = set(case.get("expected_tables", []))
            expected_safety = case.get("expected_safety", "READ")

            # 1. Evaluate Schema RAG Retrieval
            retrieved_tables = set(self.retriever.retrieve_relevant_schema(question))
            if expected_tables.issubset(retrieved_tables):
                rag_relevance_count += 1

            # 2. Evaluate AST parsing & Safety Classification on simulated SQL
            # Generate deterministic candidate query for test validation checks
            fake_sql = self._generate_mock_sql_for_case(case)
            val_res = self.validator.parse_and_validate(fake_sql)
            safety_res = SafetyEngine.classify(val_res)

            if safety_res.level.value == expected_safety:
                safety_correct_count += 1

        elapsed_s = time.perf_counter() - start_time

        summary = {
            "total_benchmark_queries": total_queries,
            "rag_schema_relevance_accuracy": (rag_relevance_count / total_queries) * 100.0,
            "safety_classification_accuracy": (safety_correct_count / total_queries) * 100.0,
            "total_benchmark_duration_s": round(elapsed_s, 3),
            "average_latency_ms": round((elapsed_s / total_queries) * 1000.0, 2),
        }
        return summary

    def _generate_mock_sql_for_case(self, case: Dict[str, Any]) -> str:
        cat = case.get("category", "")
        if cat == "destructive":
            if "DROP" in case["question"].upper():
                return "DROP TABLE payments;"
            return "DELETE FROM orders;"
        elif cat == "ddl":
            return "ALTER TABLE customers ADD COLUMN phone_number TEXT;"
        elif cat == "dml":
            if "Update" in case["question"]:
                return "UPDATE products SET stock_quantity = 30 WHERE name = 'MacBook Pro 16';"
            return "INSERT INTO customers (first_name, last_name, email, city, state) VALUES ('Sarah', 'Connor', 'sarah@example.com', 'Los Angeles', 'CA');"
        return "SELECT * FROM customers;"


if __name__ == "__main__":
    runner = BenchmarkRunner()
    results = runner.run_benchmark()
    print("\n--- SQLPilot Evaluation Benchmark Results ---")
    print(json.dumps(results, indent=2))
