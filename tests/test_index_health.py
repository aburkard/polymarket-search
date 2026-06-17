"""Tests for generated index health checks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_index_health import IndexSpec, check_all, check_index, event_count


class TestIndexHealth(unittest.TestCase):
    def write_index(self, root: Path, filename: str, count: int) -> None:
        docs = [{"q": f"Event {i}"} for i in range(count)]
        (root / filename).write_text(json.dumps({"n": count, "docs": docs, "idx": {}}))

    def test_event_count_prefers_n(self):
        self.assertEqual(event_count({"n": 3, "docs": []}), 3)

    def test_event_count_falls_back_to_docs(self):
        self.assertEqual(event_count({"docs": [{}, {}]}), 2)

    def test_check_index_passes_healthy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_index(root, "search-data.json", 5)
            spec = IndexSpec("search-data.json", "Test index", 3, 10, 1)

            result, errors = check_index(root, spec)

            self.assertEqual(errors, [])
            self.assertEqual(result["events"], 5)

    def test_check_index_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, errors = check_index(
                Path(tmp),
                IndexSpec("missing.json", "Missing index", 1, 10, 1),
            )

            self.assertEqual(len(errors), 1)
            self.assertIn("missing", errors[0])

    def test_check_index_reports_count_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_index(root, "search-data.json", 2)
            spec = IndexSpec("search-data.json", "Test index", 3, 10, 1)

            _, errors = check_index(root, spec)

            self.assertEqual(len(errors), 1)
            self.assertIn("at least 3", errors[0])

    def test_check_index_reports_json_size_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_index(root, "search-data.json", 5)
            spec = IndexSpec("search-data.json", "Test index", 3, 10, 0.000001)

            _, errors = check_index(root, spec)

            self.assertEqual(len(errors), 1)
            self.assertIn("max is", errors[0])

    def test_check_all_aggregates_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_index(root, "a.json", 5)
            self.write_index(root, "b.json", 1)
            specs = [
                IndexSpec("a.json", "A", 3, 10, 1),
                IndexSpec("b.json", "B", 3, 10, 1),
            ]

            results, errors = check_all(root, specs)

            self.assertEqual(len(results), 2)
            self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
