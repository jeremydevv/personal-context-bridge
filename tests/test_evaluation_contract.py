import copy
import importlib.util
import unittest


class EvaluationContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('personal_context.evaluation_contract'),
                             'evaluation preflight and accounting contract is missing')
        from personal_context import evaluation_contract
        self.api=evaluation_contract
        self.case=dict(id='case-1',question='What score and submission status are recorded?',
                       requested_fields=['score','state'],
                       question_components=[dict(component='recorded score',fields=['score']),
                                            dict(component='submission status',fields=['state'])],
                       criteria=[dict(field='score',expected=17,source_ids=['source-a']),
                                 dict(field='state',expected='submitted',source_ids=['source-a'])],
                       source_cluster_ids=['cluster-a'])

    def test_every_requested_component_requires_a_criterion(self):
        self.assertTrue(self.api.validate_cases([self.case])['valid'])
        bad=copy.deepcopy(self.case);bad['criteria'].pop()
        with self.assertRaisesRegex(ValueError,'criterion_field_mismatch'):
            self.api.validate_cases([bad])
        bad=copy.deepcopy(self.case);bad['question_components'].append(dict(component='due date',fields=['due']))
        with self.assertRaisesRegex(ValueError,'component_field_mismatch'):
            self.api.validate_cases([bad])

    def test_duplicates_unknown_without_reason_and_source_overlap_fail(self):
        with self.assertRaisesRegex(ValueError,'duplicate_case'):
            self.api.validate_cases([self.case,self.case])
        bad=copy.deepcopy(self.case);bad['criteria'][0]['expected']=None
        with self.assertRaisesRegex(ValueError,'unknown_requires_reason'):
            self.api.validate_cases([bad])
        with self.assertRaisesRegex(ValueError,'heldout_source_overlap'):
            self.api.validate_cases([self.case],forbidden_source_clusters={'cluster-a'})
        bad['criteria'][0]['absence_reason']='The original contains no recorded score.'
        self.assertTrue(self.api.validate_cases([bad])['valid'])

    def test_holdout_iterator_protects_later_cases(self):
        first=copy.deepcopy(self.case)
        first['id']='clean-case';first['source_cluster_ids']=['cluster-b']
        with self.assertRaisesRegex(ValueError,'heldout_source_overlap'):
            self.api.validate_cases([first,self.case],forbidden_source_clusters=iter(['cluster-a']))

    def test_unhashable_case_identity_is_rejected_explicitly(self):
        bad=copy.deepcopy(self.case);bad['id']=[]
        with self.assertRaisesRegex(ValueError,'invalid_case_id'):
            self.api.validate_cases([bad])

    def test_reference_anchor_and_no_extra_answer_fields(self):
        bad=copy.deepcopy(self.case);bad['criteria'][0]['source_ids']=[]
        with self.assertRaisesRegex(ValueError,'missing_source_anchor'):
            self.api.validate_cases([bad])
        bad=copy.deepcopy(self.case);bad['criteria'].append(dict(field='unasked',expected=3,source_ids=['x']))
        with self.assertRaisesRegex(ValueError,'criterion_field_mismatch'):
            self.api.validate_cases([bad])

    def test_numeric_format_is_not_factual_error_but_units_matter(self):
        self.assertEqual(self.api.numeric_check('$10,000/month',10000,unit='USD/month')['status'],'match')
        self.assertEqual(self.api.numeric_check('70%',70,unit='percent')['status'],'match')
        self.assertEqual(self.api.numeric_check('$10,000/year',10000,unit='USD/month')['status'],'unit_mismatch')
        self.assertEqual(self.api.numeric_check('70%',.7,unit='percent')['status'],'mismatch')
        self.assertEqual(self.api.numeric_check('15/15',15,unit='points')['status'],'ambiguous_format')
        self.assertEqual(self.api.numeric_check(True,1)['status'],'ambiguous_format')

    def test_numeric_missing_zero_and_unsupported_suffix_are_distinct(self):
        self.assertEqual(self.api.numeric_check(None,0)['status'],'ambiguous_format')
        self.assertEqual(self.api.numeric_check('0',0)['status'],'match')
        self.assertEqual(self.api.numeric_check('0 kg',0,unit='count')['status'],'unit_mismatch')
        self.assertEqual(self.api.numeric_check('nan',0)['status'],'ambiguous_format')
        self.assertEqual(self.api.numeric_check('-1.25',-1.25)['status'],'match')

    def test_call_accounting_counts_planning_answering_and_cache(self):
        rows=[dict(stage='planning',status='complete',usage=dict(input_tokens=100,output_tokens=20,total_tokens=120,input_tokens_details=dict(cached_tokens=30))),
              dict(stage='answer',status='complete',usage=dict(input_tokens=200,output_tokens=40,total_tokens=240))]
        result=self.api.account_calls(rows)
        self.assertEqual(result['total_tokens'],360);self.assertEqual(result['cached_input_tokens'],30)
        self.assertEqual(result['calls'],2);self.assertFalse(result['cost_complete'] is False)
        rows.append(dict(stage='answer',status='failed',usage=None))
        result=self.api.account_calls(rows)
        self.assertEqual(result['failed_calls'],1);self.assertEqual(result['calls_missing_usage'],1)
        self.assertFalse(result['cost_complete']);self.assertEqual(result['total_tokens'],360)

    def test_invalid_usage_is_rejected_instead_of_zero_cost(self):
        for usage in [dict(input_tokens=10,output_tokens=2,total_tokens=1),
                      dict(input_tokens=True,output_tokens=2,total_tokens=3),
                      dict(input_tokens=10,output_tokens=2,total_tokens=12,input_tokens_details=dict(cached_tokens=20))]:
            with self.assertRaises(ValueError):self.api.account_calls([dict(stage='answer',status='complete',usage=usage)])
        with self.assertRaisesRegex(ValueError,'completed_call_missing_usage'):
            self.api.account_calls([dict(stage='answer',status='complete',usage=None)])


if __name__=='__main__':unittest.main()
