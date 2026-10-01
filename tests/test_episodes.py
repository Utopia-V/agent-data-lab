import unittest
from pathlib import Path
import tempfile
import json

from agent_data_lab.episodes import grade_currency
from agent_data_lab.workflow import read_artifact,delivered_path,artifact_file,capture_artifacts


class CurrencyGrading(unittest.TestCase):
    def test_artifact_consumption_and_capture_reject_links_outside_the_work_area(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);scratch=root/'scratch';scratch.mkdir()
            external=root/'host.json';external.write_text('{"answer":"not a model result"}')
            (scratch/'result.json').symlink_to(external)
            with self.assertRaises(ValueError):artifact_file(scratch,'result.json')
            with self.assertRaises(ValueError):capture_artifacts(scratch,root/'capture')
            self.assertFalse((root/'capture').exists())

    def test_task_artifacts_are_independent_and_wrong_delivery_path_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'results').mkdir()
            for index,answer in enumerate(('old','new')):
                (root/f'results/{index}.json').write_text(json.dumps({'answer':answer}))
            self.assertEqual(read_artifact(root,'results/0.json')['answer'],'old')
            self.assertEqual(read_artifact(root,'results/1.json')['answer'],'new')
            with self.assertRaises(ValueError): read_artifact(root,'results/2.json')
            self.assertFalse(delivered_path('{"result_path":"/scratch/results/0.json"}','/scratch/results/1.json'))
            self.assertTrue(delivered_path('{"result_path":"/scratch/results/1.json"}','/scratch/results/1.json'))

    def test_optional_currency_does_not_change_numeric_answer(self):
        for answer in ('0.123217','EUR 0.123217'):
            self.assertTrue(grade_currency(answer,'0.123217')['correct'])
        for answer in ('EUR 0.064000','cannot determine','0.123217 or 0.064000','0.1232'):
            self.assertFalse(grade_currency(answer,'0.123217')['correct'])


if __name__=='__main__': unittest.main()
