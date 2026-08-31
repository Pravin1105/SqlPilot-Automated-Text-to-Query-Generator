from eval.runner import BenchmarkRunner


def test_benchmark_runner_execution():
    runner = BenchmarkRunner()
    results = runner.run_benchmark()
    assert results["total_benchmark_queries"] > 0
    assert results["rag_schema_relevance_accuracy"] == 100.0
    assert results["safety_classification_accuracy"] == 100.0
