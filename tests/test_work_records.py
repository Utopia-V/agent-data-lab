from pathlib import Path
import json
import tempfile
import unittest

from agent_data_lab.work_records import WorkIndex, prepare_records, render_document


class WorkRecords(unittest.TestCase):
    def test_scope_and_recorded_dependencies_survive_a_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, work = root / "source", root / "work"
            source.mkdir(); work.mkdir()
            (source / "rules.md").write_text("rate / 10000")
            (source / "other.md").write_text("other")
            (work / "analysis.json").write_text('{"amount": 4}')
            records = [{"id": "analysis", "title": "分析", "purpose": "计算费用", "limits": "按此来源单位",
                        "entrypoint": "读取 analysis.json", "artifacts": ["analysis.json"],
                        "sources": ["rules.md"], "depends_on": []}]
            prepared = prepare_records(records, source, work)
            file = work / "index.json"
            file.write_text(json.dumps(prepared))
            index = WorkIndex(file, source, work)
            self.assertEqual(index.select(ids=[]), [])
            self.assertEqual(index.changes(), [])
            (source / "other.md").write_text("changed, but no dependency was declared")
            self.assertEqual(index.changes(), [])
            (source / "rules.md").write_text("rate / 1000")
            self.assertEqual([(item["work"], item["path"]) for item in index.changes()], [("analysis", "rules.md")])
            self.assertEqual(json.loads(Path(index.artifacts()[0]["path"]).read_text()), {"amount": 4})
            (source / "rules.md").unlink()
            self.assertIsNone(index.changes()[0]["after"])
            with self.assertRaises(KeyError):
                index.select(ids=["unknown"])

    def test_document_and_structure_receive_the_same_description(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fact.md").write_text("fact")
            (root / "output.json").write_text("{}")
            raw = [{"id": "result", "title": "结果", "purpose": "用途", "limits": "范围",
                    "entrypoint": "入口", "artifacts": ["output.json"], "sources": ["fact.md"],
                    "depends_on": [], "unshared_extra": "not part of the accepted description"}]
            records = prepare_records(raw, root, root)
            self.assertNotIn("unshared_extra", records[0])
            document = render_document(records)
            for text in ["result", "结果", "用途", "范围", "入口", "output.json", "fact.md", records[0]["sources"][0]["revision"]]:
                self.assertIn(text, document)


if __name__ == "__main__":
    unittest.main()
