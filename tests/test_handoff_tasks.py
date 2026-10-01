import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from agent_data_lab.handoff_tasks import TASKS, grade


class HandoffDelivery(unittest.TestCase):
    def test_current_values_and_each_csv_value_must_agree(self):
        task = TASKS[-1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = copy.deepcopy(task["expected"])
            def write_csv(values):
                with (root / "delivery.csv").open("w") as file:
                    writer = csv.writer(file)
                    writer.writerow(["section", "key", "value"])
                    for section, fields in values.items():
                        for key, value in fields.items():
                            writer.writerow([section, key, json.dumps(value)])
            write_csv(actual)
            self.assertTrue(grade(task, actual, root)["correct"])
            stale = copy.deepcopy(actual)
            stale["resources"]["hold_ms"] = 3600000
            write_csv(stale)
            self.assertEqual(grade(task, actual, root)["errors"], ["csv_values"])
            write_csv(actual)
            self.assertEqual(grade(task, stale, root)["errors"], ["resources", "csv_values"])

    def test_composition_preserves_allowed_source_explanations(self):
        task = TASKS[-1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = copy.deepcopy(task["expected"])
            actual["parameter_filters"]["sources"] = ["protocol.ts", "previous-result.json"]
            with (root / "delivery.csv").open("w") as file:
                writer = csv.writer(file)
                writer.writerow(["section", "key", "value"])
                for section, fields in actual.items():
                    for key, value in fields.items():
                        writer.writerow([section, key, json.dumps(value)])
            self.assertTrue(grade(task, actual, root)["correct"])
            actual["parameter_filters"]["requires_base"].append("incorrect.method")
            self.assertIn("parameter_filters", grade(task, actual, root)["errors"])


if __name__ == "__main__":
    unittest.main()
