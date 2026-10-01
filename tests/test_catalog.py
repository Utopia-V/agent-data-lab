import json
from pathlib import Path
import tempfile
import unittest

from agent_data_lab.catalog import Catalog


class CatalogBehavior(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'source'; self.root.mkdir()
        self.cache=Path(self.temp.name)/'cache'
        (self.root/'data.csv').write_text('item,amount\na,3\nb,7\n')
        (self.root/'rules.json').write_text('[{"kind":"x","allowed":[],"rate":3}]')
        (self.root/'manual.md').write_text('# Guide\n\nIntro.\n\n## Formula\n\nAmount uses the rule rate.\n\n## Other\n\nUnrelated content.\n')

    def tearDown(self): self.temp.cleanup()

    def test_source_discovery_supplies_schema_and_source_samples(self):
        catalog=Catalog(self.root,self.cache)
        try:
            rows={row['path']:row for row in catalog.sources()}
            self.assertEqual(rows['data.csv']['rows'],2)
            self.assertEqual([x['name'] for x in rows['data.csv']['columns']],['item','amount'])
            self.assertEqual(rows['data.csv']['sample'],[{'item':'a','amount':3},{'item':'b','amount':7}])
            hits=catalog.find('Formula')['matches']
            self.assertEqual(hits[0]['path'],'manual.md')
            self.assertIn('Amount uses',hits[0]['text'])
            self.assertNotIn('Unrelated',hits[0]['text'])
        finally: catalog.close()

    def test_selection_reports_omitted_candidates_and_keeps_unprofiled_sources(self):
        (self.root/'extra.md').write_text('# Another formula\n\nAnother rule rate.\n')
        (self.root/'unknown.bin').write_bytes(b'\x00')
        catalog=Catalog(self.root,self.cache)
        try:
            result=catalog.find('formula',limit=1)
            self.assertEqual(len(result['matches']),1)
            self.assertEqual(result['match_count'],2)
            self.assertTrue(result['truncated'])
            empty=catalog.find('!!!')
            self.assertEqual(empty['matches'],[])
            self.assertEqual(empty['unprofiled'][0]['path'],'unknown.bin')
        finally: catalog.close()

    def test_profiles_and_locations_update_across_process_lifetimes(self):
        catalog=Catalog(self.root,self.cache)
        before=catalog.read('manual.md')['revision']
        catalog.close()
        (self.root/'data.csv').write_text('item,amount\na,3\nb,7\nc,11\n')
        (self.root/'manual.md').write_text('# Guide\n\n## Revised\n\nThe formula changed.\n')
        catalog=Catalog(self.root,self.cache)
        try:
            self.assertEqual(next(p['rows'] for p in catalog.sources() if p['path']=='data.csv'),3)
            self.assertEqual(catalog.find('Revised')['matches'][0]['line'],3)
            with self.assertRaisesRegex(ValueError,'revision changed'):
                catalog.read('manual.md',revision=before)
        finally: catalog.close()

    def test_broken_derived_cache_is_rebuilt_without_losing_native_sources(self):
        catalog=Catalog(self.root,self.cache);catalog.close()
        (self.cache/'sources.json').write_text('{unfinished')
        (self.cache/'text.sqlite').write_bytes(b'not a database')
        catalog=Catalog(self.root,self.cache)
        try:
            self.assertEqual(catalog.find('Formula')['matches'][0]['path'],'manual.md')
            self.assertEqual((self.root/'data.csv').read_text(),'item,amount\na,3\nb,7\n')
        finally:catalog.close()

    def test_unprofiled_sources_remain_visible_and_removal_invalidates_search(self):
        (self.root/'unknown.bin').write_bytes(b'\x00binary')
        catalog=Catalog(self.root,self.cache)
        try:
            self.assertEqual(catalog.find('Formula')['unprofiled'][0]['path'],'unknown.bin')
            (self.root/'manual.md').unlink()
            self.assertEqual(catalog.find('Formula')['matches'],[])
            self.assertNotIn('manual.md',[x['path'] for x in catalog.sources()])
        finally: catalog.close()

    def test_chinese_question_matches_words_without_changing_source_text(self):
        source='# 来源说明\n\n## 学习语境\n\n学习语境由官方学习能力持续维护。\n'
        (self.root/'中文.md').write_text(source)
        catalog=Catalog(self.root,self.cache)
        try:
            matches=catalog.find('学习语境应该由谁负责维护')['matches']
            self.assertEqual(matches[0]['path'],'中文.md')
            self.assertEqual(matches[0]['text'],'## 学习语境\n\n学习语境由官方学习能力持续维护。')
        finally: catalog.close()

    def test_unavailable_link_remains_visible_and_cannot_import_content_from_outside_root(self):
        external=Path(self.temp.name)/'private.txt'; external.write_text('UNAUTHORIZED_SENTINEL')
        (self.root/'linked.txt').symlink_to(external)
        (self.root/'missing.txt').symlink_to(self.root/'absent.txt')
        catalog=Catalog(self.root,self.cache)
        try:
            result=catalog.find('UNAUTHORIZED_SENTINEL')
            self.assertEqual(result['matches'],[])
            self.assertEqual({item['path'] for item in result['unprofiled']},{'linked.txt','missing.txt'})
            (self.root/'linked.txt').unlink()
            (self.root/'linked.txt').write_text('Now an ordinary available source.')
            self.assertEqual(catalog.find('available')['matches'][0]['path'],'linked.txt')
        finally: catalog.close()


if __name__=='__main__': unittest.main()
