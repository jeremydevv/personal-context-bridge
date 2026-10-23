import json
import unittest


class SummaryContextTests(unittest.TestCase):
 def setUp(self):
  self.items=[dict(title='Other',text='No score.',metadata=dict(course_id=1)),
              dict(title='Lab',text='Score 17. Pencil required.',metadata=dict(course_id=22,score=17,submitted=False,attempt=0,submitted_at=None))]
  self.refs=[dict(kind='canvas_assignment',id=str(i),digest='v1') for i in range(2)]
  self.value=dict(overview='Lab',facts=[dict(text='Score 17',sources=[1])],actions=[],topics=[],uncertainties=[])
 def prepare(self,source='canvas_assignment',**kwargs):
  from personal_context.summary_context import prepare_summary_context
  return prepare_summary_context(source,self.value,self.items,self.refs,**kwargs)
 def test_one_read_has_typed_context_and_exact_original_identity(self):
  value=self.prepare(question='Pencil required?',limit=1)
  original=value['original_selection']['items'][0]
  self.assertEqual(original['index'],1)
  self.assertEqual(original['evidence_id'],value['summary']['facts'][0]['evidence_ids'][0])
  self.assertEqual(value['source_catalog'][1]['metadata'],self.items[1]['metadata'])
  self.assertEqual(value['original_selection']['inference_calls'],0)
  self.assertFalse(value['original_selection']['coverage_complete'])
  self.assertEqual(value['semantic_support'],'not_checked')
 def test_health_removes_only_exact_duplicate_and_preserves_all_statistics(self):
  stats=dict(type='Steps',device='Phone',date='2026-01-02',sample_sum=0,verified=False,
             category=None,sampled_statistics_not_deduplicated_totals=True)
  self.items[0]['text']=json.dumps(stats)
  value=self.prepare(source='health')
  self.assertEqual(value['generation_method'],'deterministic_sampled_health_v1')
  self.assertEqual(json.loads(value['summary']['facts'][0]['text']),stats)
  self.assertNotIn('structured_body',value['source_catalog'][0])
  self.assertEqual(value['deduplicated_statistics_objects'],1)
  self.assertEqual(value['source_catalog'][1]['metadata'],self.items[1]['metadata'])
  self.assertIn('non-statistic',' '.join(value['summary']['uncertainties']))
 def test_coalescing_moves_only_exact_duplicate_metadata_to_original(self):
  from personal_context.summary_context import coalesce_catalog_metadata
  from personal_context.evidence_contract import evidence_catalog,resolve_evidence
  catalog=evidence_catalog(self.items,self.refs)
  reads=resolve_evidence([catalog[1]['evidence_id']],self.items,self.refs)
  compact,count=coalesce_catalog_metadata(catalog,reads)
  self.assertEqual(count,1)
  self.assertEqual(compact[1]['metadata_in_original_evidence'],catalog[1]['evidence_id'])
  self.assertNotIn('metadata',compact[1])
  self.assertEqual(compact[0],catalog[0])
  self.assertEqual(reads[0]['evidence']['metadata'],self.items[1]['metadata'])
  self.assertIn('metadata',catalog[1])
  reads[0]['evidence']['metadata']['attempt']=False
  different,count=coalesce_catalog_metadata(catalog,reads)
  self.assertEqual(count,0);self.assertIn('metadata',different[1])
 def test_coalescing_cannot_hide_unknown_or_unreturned_metadata(self):
  from personal_context.summary_context import coalesce_catalog_metadata
  from personal_context.evidence_contract import evidence_catalog
  catalog=evidence_catalog(self.items,self.refs)
  compact,count=coalesce_catalog_metadata(catalog,[])
  self.assertEqual(compact,catalog);self.assertEqual(count,0)
  compact,count=coalesce_catalog_metadata(catalog,[dict(evidence_id='ev1_unknown',evidence=self.items[1])])
  self.assertEqual(compact,catalog);self.assertEqual(count,0)
 def test_budget_coalescing_retains_original_body_and_all_typed_metadata(self):
  self.items[1]['metadata']['large']='x'*6000
  base=self.prepare();limit=len(json.dumps(base,ensure_ascii=False,sort_keys=True,separators=(',',':')))+1800
  packed=self.prepare(question='Pencil',limit=1,max_characters=limit)
  self.assertEqual(len(packed['original_selection']['items']),1)
  read=packed['original_selection']['items'][0]
  self.assertEqual(read['evidence']['metadata'],self.items[1]['metadata'])
  self.assertEqual(packed['source_catalog'][1]['metadata_in_original_evidence'],read['evidence_id'])
  self.assertLessEqual(len(json.dumps(packed,ensure_ascii=False,sort_keys=True,separators=(',',':'))),limit)
 def test_budget_does_not_silently_drop_catalog_or_claims(self):
  with self.assertRaisesRegex(ValueError,'paged_reads'):
   self.prepare(max_characters=100)
 def test_whole_payload_budget_reports_unreturned_originals(self):
  self.items[1]['text']='Pencil required. '+('x'*5000)
  base=self.prepare();limit=len(json.dumps(base,ensure_ascii=False,sort_keys=True,separators=(',',':')))+1200
  result=self.prepare(question='Pencil',max_characters=limit)
  self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'))),limit)
  self.assertEqual(len(result['source_catalog']),2)
  self.assertEqual(result['summary']['facts'][0]['text'],'Score 17')
  self.assertGreater(result['original_selection']['candidate_items_not_returned'],0)
  self.assertFalse(result['original_selection']['coverage_complete'])

if __name__=='__main__':unittest.main()
