import unittest
from copy import deepcopy
from relay_core.case_contracts import lifecycle, transition

class CaseContracts(unittest.TestCase):
    def setUp(self):
        self.definition={'fields':{'type':'object','properties':{'note':{'type':'string'},'completion_evidence':{'type':'string'}}},
            'priority':'High','initial_stage':'open','stages':[
                {'key':'open','label':'Open','state':'open','next':['waiting','completed']},
                {'key':'waiting','label':'Waiting on Party','state':'waiting'},
                {'key':'completed','label':'Completed','state':'done','required_fields':['completion_evidence'],'next':[]}]}
    def test_completion_evidence_and_transition_rules(self):
        self.assertEqual(transition(self.definition,'waiting',{'note':'Call tomorrow'},'open')[1],'waiting')
        for evidence in ('','   '):
            with self.assertRaises(ValueError):transition(self.definition,'completed',{'completion_evidence':evidence},'open')
        self.assertEqual(transition(self.definition,'completed',{'completion_evidence':'Catalogue sent'},'open')[1],'done')
        with self.assertRaises(ValueError):transition(self.definition,'open',{},'completed')
    def test_invalid_schema_states_references_and_extra_values(self):
        for mutate in (lambda d:d.update(initial_stage='absent'),lambda d:d.update(priority='Urgent'),lambda d:d['stages'][0].update(next=['absent']),lambda d:d['stages'][0].update(required_fields=['absent']),lambda d:d['stages'][0].update(state='unknown')):
            value=deepcopy(self.definition);mutate(value)
            with self.assertRaises(ValueError):lifecycle(value)
        with self.assertRaises(ValueError):transition(self.definition,'open',{'arbitrary':True})
