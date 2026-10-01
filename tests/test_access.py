import json
from pathlib import Path
import random
import tempfile
import unittest

from agent_data_lab.access import ReadFailure, Space
from agent_data_lab.fixtures import generate, write_json
from agent_data_lab.sandbox import Sandbox
from agent_data_lab.cli import grade


class AccessBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "corpus"
        self.tasks = {task.id: task for task in generate(self.root, 17, 40)}
        self.space = Space(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def documents(self):
        return [row["ref"] for row in self.space.objects() if row["kind"] == "markdown" and ":" not in row["ref"]]

    def target(self):
        return self.tasks["lookup"].prompt.split()[1].split("，")[0]

    def test_reference_occurrences_match_creation_facts_across_seeds(self):
        for seed in (3, 99, 742):
            with self.subTest(seed=seed):
                root = Path(self.temp.name) / str(seed)
                tasks = {task.id: task for task in generate(root, seed, 60)}
                space = Space(root)
                target = tasks["lookup"].prompt.split()[1].split("，")[0]
                scope = [row["ref"] for row in space.objects() if row["kind"] == "markdown" and ":" not in row["ref"]]
                result = space.references_to(target, within=scope)
                actual = [f"{row['ref']}@{row['line']}:{row['ordinal']}" for row in result["items"]]
                self.assertCountEqual(actual, tasks["references"].answers)
                self.assertTrue(result["complete"])

    def test_native_query_composes_with_scoped_search_and_read(self):
        rows = self.space.sql("SELECT a.question_ref FROM attempts a WHERE a.correct=0 AND a.seq=(SELECT MAX(b.seq) FROM attempts b WHERE b.question_ref=a.question_ref)")
        scope = [row["question_ref"] for row in rows]
        self.assertCountEqual(scope, self.tasks["latest"].answers)
        result = self.space.search("写回路径", within=scope, limit=3)
        self.assertEqual([row["ref"] for row in result["items"]], self.tasks["scoped"].answers)
        full = self.space.search("写回路径", within=scope)
        output = []
        for hit in full["items"]:
            text = self.space.read(hit["ref"], revision=hit["revision"])["text"]
            token = next(line.split("：")[1] for line in text.splitlines() if line.startswith("校验词："))
            output.append(hit["ref"] + "=" + token)
        self.assertCountEqual(output, self.tasks["join"].answers)
        self.assertGreater(full["matched_count"], len(result["items"]))
        self.assertTrue(result["truncated"])

    def test_empty_and_duplicate_scope_do_not_expand_or_multiply(self):
        target = self.target()
        self.assertEqual(self.space.search("写回路径", within=[])["items"], [])
        self.assertEqual(self.space.references_to(target, within=[])["covered"], [])
        scope = self.documents()
        expected = self.space.references_to(target, within=scope)
        actual = self.space.references_to(target, within=scope + scope)
        self.assertEqual(actual, expected)
        random.Random(4).shuffle(scope)
        self.assertEqual(self.space.references_to(target, within=scope)["items"], expected["items"])

    def test_uncovered_objects_survive_and_raw_fallback_is_available(self):
        target = self.target()
        result = self.space.references_to(target)
        unresolved = {row["ref"]: row["reason"] for row in result["unresolved"]}
        self.assertEqual(unresolved, {"missing:17": "missing", "broken:17": "invalid_utf8", "opaque:17": "unsupported_reference_query"})
        self.assertFalse(result["complete"])
        self.assertIn(target, self.space.read("opaque:17")["text"])
        record_hits = [row for row in result["items"] if row["ref"].startswith("annotation:")]
        self.assertEqual([row["ref"] for row in record_hits], ["annotation:n0", "annotation:n12", "annotation:n15", "annotation:n3", "annotation:n6", "annotation:n9"])

    def test_move_preserves_identity_and_edit_invalidates_old_location(self):
        ref = self.documents()[0]
        before = self.space.read(ref)
        entries = self.space.objects()
        entry = next(row for row in entries if row["ref"] == ref)
        moved = self.root / "renamed.md"
        (self.root / entry["path"]).rename(moved)
        entry["path"] = "renamed.md"
        write_json(self.root / "inventory.json", entries)
        self.assertEqual(self.space.read(ref), before)
        moved.write_text("插入一行\n" + before["text"])
        with self.assertRaisesRegex(ReadFailure, "stale_revision"):
            self.space.read(ref, lines=(1, 2), revision=before["revision"])
        self.assertNotEqual(self.space.read(ref)["revision"], before["revision"])

    def test_unknown_identity_and_broken_record_source_are_not_zero(self):
        self.assertEqual(self.space.search("x", within=["absent"])["unresolved"], [{"ref":"absent", "reason":"unknown"}])
        (self.root / "annotations.jsonl").write_text("{not json}\n")
        result = self.space.references_to(self.target(), within=["annotation:n0"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["unresolved"][0]["reason"], "unreadable_source")

    def test_scope_precedes_limit_and_zero_limit_preserves_match_count(self):
        scope = self.documents()
        all_matches = self.space.search("写回路径", within=scope)
        chosen = all_matches["items"][-1]["ref"]
        result = self.space.search("写回路径", within=[chosen], limit=1)
        self.assertEqual(result["items"][0]["ref"], chosen)
        zero = self.space.search("写回路径", within=scope, limit=0)
        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["matched_count"], all_matches["matched_count"])
        self.assertTrue(zero["truncated"])

    def test_model_program_can_batch_but_cannot_read_host_or_oracle(self):
        secret = Path(self.temp.name) / "oracle.json"
        secret.write_text("not available to model")
        sandbox = Sandbox(self.root, Path(self.temp.name) / "scratch", interface=True)
        code = "from access import Space; import pathlib; s=Space(); print(len(s.objects())); print(pathlib.Path(" + repr(str(secret)) + ").exists()); print(len(s.sql('select * from attempts')))"
        import shlex
        result = sandbox.run("python3 -c " + shlex.quote(code))
        self.assertEqual(result["exit_code"], 0, result["output"])
        self.assertEqual(result["output"].splitlines(), [str(len(self.space.objects())), "False", "80"])
        trunc = sandbox.run("python3 -c 'print(\"x\"*3000)'", max_chars=1000)
        self.assertTrue(trunc["truncated"])
        self.assertEqual(len(trunc["output"]), 1000)

    def test_grader_rejects_missing_and_repeated_items_and_wrong_coverage(self):
        task = self.tasks["mixed"]
        good = {"answers": task.answers, "unresolved": task.unresolved}
        self.assertTrue(grade(json.dumps(good), task)["correct"])
        for bad in [dict(good, answers=task.answers[:-1]), dict(good, answers=task.answers*2), dict(good, unresolved=[])]:
            self.assertFalse(grade(json.dumps(bad), task)["correct"])


if __name__ == "__main__":
    unittest.main()
