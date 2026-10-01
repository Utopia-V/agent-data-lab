from pathlib import Path
import tempfile
import unittest

from agent_data_lab.observations import source_changes,source_snapshot


class SourceObservations(unittest.TestCase):
    def test_unavailable_source_is_never_reported_as_an_observed_empty_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir()
            (Path(temporary)/'private.txt').write_text('UNAUTHORIZED_SENTINEL')
            (root/'link.txt').symlink_to(Path(temporary)/'private.txt')
            after=source_snapshot(root)
            self.assertIsNone(after['link.txt']['revision'])
            self.assertNotIn('text',after['link.txt'])
            result=source_changes(after,after)
            self.assertEqual(result['changes'],[])
            self.assertEqual(result['unavailable'][0]['path'],'link.txt')

    def test_changes_distinguish_text_diff_data_change_removal_and_unmodified_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'manual.md').write_text('Fee = rate / 10000\n')
            (root/'large.csv').write_text('0\n'*40000)
            (root/'move.txt').write_text('same content')
            (root/'keep.txt').write_text('unchanged')
            before=source_snapshot(root)
            (root/'manual.md').write_text('Fee = rate / 1000\n')
            (root/'large.csv').write_text('1\n'*40000)
            (root/'move.txt').rename(root/'moved.txt')
            result=source_changes(before,source_snapshot(root))
            changes={item['path']:item for item in result['changes']}
            self.assertIn('-Fee = rate / 10000',changes['manual.md']['diff'])
            self.assertIn('+Fee = rate / 1000',changes['manual.md']['diff'])
            self.assertNotIn('diff',changes['large.csv'])
            self.assertEqual(changes['move.txt']['change'],'removed')
            self.assertEqual(changes['moved.txt']['change'],'added')
            self.assertEqual(result['unchanged_count'],1)
            self.assertEqual(source_changes(before,before)['changes'],[])


if __name__=='__main__': unittest.main()
