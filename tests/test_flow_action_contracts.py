import unittest
from relay_core.flows.action_contracts import inputs

class ActionContracts(unittest.TestCase):
    def setUp(self):
        self.schema={'type':'object','required':['count'],'properties':{
            'count':{'type':'integer','minimum':1,'maximum':5},
            'choices':{'type':'array','items':{'type':'string','enum':['Red','Blue']}}}}
    def test_resolves_typed_answers_without_executing_text(self):
        result=inputs({'count':{'var':'quantity'},'choices':{'var':'colors'}},self.schema,{'quantity':2,'colors':['Blue']})
        self.assertEqual(result,{'count':2,'choices':['Blue']})
    def test_rejects_coercion_unknown_fields_missing_answers_and_bad_choices(self):
        for value in ({'count':True},{'count':'2'},{'count':6},{'count':float('nan')},{'count':2,'method':'os.system'},{'count':{'var':'missing'}},{'count':2,'choices':['Green']},{}):
            with self.assertRaises(ValueError):inputs(value,self.schema,{})
    def test_bounds_nested_inputs_and_resolved_values(self):
        value='x'
        for _ in range(10):value={'nested':value}
        with self.assertRaises(ValueError):inputs(value,self.schema,{})
        with self.assertRaises(ValueError):inputs({'count':{'var':'quantity'}},self.schema,{'quantity':2.0})

    def test_resolved_answers_are_bounded_literal_data(self):
        schema={'type':'object','properties':{'value':{'type':'object','properties':{'var':{'type':'string'}}}}}
        self.assertEqual(inputs({'value':{'var':'answer'}},schema,{'answer':{'var':'literal'}}),{'value':{'var':'literal'}})
        with self.assertRaises(ValueError):
            inputs({'value':{'var':'answer'}},schema,{'answer':{'var':'x'*10001}})

    def test_schema_rejects_unsupported_and_malformed_constraints(self):
        from relay_core.flows.action_contracts import check_schema
        self.assertEqual(check_schema(self.schema),self.schema)
        for schema in ({'type':'string','pattern':'unsafe ignored constraint'},
                       {'type':'array'}, {'type':'object','required':['missing']},
                       {'type':'object','additionalProperties':True},
                       {'type':'string','maxLength':'10'},
                       {'type':'string','minLength':5,'maxLength':2},
                       {'type':'integer','enum':[True]},
                       {'type':'number','maximum':float('inf')}):
            with self.assertRaises(ValueError):check_schema(schema)

    def test_bounded_json_retains_nested_collected_values(self):
        from relay_core.flows.action_contracts import check_schema
        schema={'type':'object','additionalProperties':{'type':'json'}}
        check_schema(schema)
        value={'colors':['Red','Blue'],'quantity':2,'details':{'accepted':True}}
        self.assertEqual(inputs(value,schema,{}),value)
        with self.assertRaises(ValueError):inputs({'bad':float('nan')},schema,{})
