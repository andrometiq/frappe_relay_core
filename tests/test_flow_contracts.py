import unittest
from relay_core.flows.contracts import definition,parse_input,render

class FlowContracts(unittest.TestCase):
 def test_rejects_code_unknown_steps_and_uncollected_variables(self):
  for nodes in ([],[{'id':'run','kind':'python','text':'execute'}],[{'id':'reply','kind':'reply','text':'{{unknown}}'}],[{'id':'reply','kind':'reply','text':'x','url':'https://invalid'}]):
   with self.assertRaises(ValueError):definition(nodes)
 def test_input_types_and_literal_rendering(self):
  for kind,value in [('number','NaN'),('number','inf'),('date','2026-02-30'),('email','a@bad'),('choice','other')]:
   with self.assertRaises(ValueError):parse_input({'input_type':kind,'choices':['Yes','No']},value)
  self.assertEqual(parse_input({'input_type':'choice','choices':['Yes','No']},'yes'),'Yes')
  self.assertEqual(parse_input({'input_type':'date'},'2026-09-23'),'2026-09-23')
  self.assertEqual(render('Hello {{name}}',{'name':'{{do_not_execute}}'}),'Hello {{do_not_execute}}')
 def test_valid_linear_definition_and_bounds(self):
  nodes=[{'id':'name','kind':'input','text':'Your name?','variable':'name','input_type':'text'}, {'id':'reply','kind':'reply','text':'Hello {{name}}'}]
  self.assertEqual(definition(nodes),nodes)
  with self.assertRaises(ValueError):definition(nodes+[nodes[0]])
  with self.assertRaises(ValueError):parse_input(nodes[0],'x'*1001)
  with self.assertRaises(ValueError):render('{{x}}'*5,{'x':'a'*1000})

 def test_branches_reject_backward_jumps_and_skipped_inputs(self):
  from relay_core.flows.contracts import matches
  nodes=[{'id':'age','kind':'input','text':'Age?','variable':'age','input_type':'number'},
   {'id':'choice','kind':'condition','variable':'age','operator':'gte','value':'18','then':'adult','otherwise':'minor'},
   {'id':'adult','kind':'end'},{'id':'minor','kind':'end'}]
  definition(nodes)
  self.assertTrue(matches(nodes[1],{'age':'21'}));self.assertFalse(matches(nodes[1],{'age':'NaN'}));self.assertFalse(matches(nodes[1],{'age':'12'}))
  nodes[1]['then']='age'
  with self.assertRaises(ValueError):definition(nodes)
  nodes[1]['then']='extra';nodes[1]['otherwise']='use'
  nodes[2:] = [{'id':'extra','kind':'input','text':'Name?','variable':'name','input_type':'text'},{'id':'use','kind':'reply','text':'Hi {{name}}'}]
  with self.assertRaises(ValueError):definition(nodes)
  for seconds in (0,86401,True):
   with self.assertRaises(ValueError):definition([{'id':'wait','kind':'wait','seconds':seconds}])

 def test_numeric_bounds_optional_and_multiple_choices(self):
  node={'input_type':'number','minimum':0,'maximum':100,'integer_only':True}
  for invalid in ('-1','101','1.5'):
   with self.assertRaises(ValueError):parse_input(node,invalid)
  self.assertEqual(parse_input(node,'42'),'42')
  self.assertEqual(parse_input({**node,'optional':True},'skip'),'')
  choices={'input_type':'multi_choice','choices':['Red','Blue','Green']}
  self.assertEqual(parse_input(choices,'1,3,1'),['Red','Green'])
  self.assertEqual(parse_input(choices,'["blue","Green"]'),['Blue','Green'])
  with self.assertRaises(ValueError):parse_input(choices,'4')
  self.assertEqual(render('Selected {{colors}}',{'colors':['Red','Green']}),'Selected Red, Green')

 def test_topic_titles_require_collected_inputs_and_valid_status(self):
  topic={'id':'topic','kind':'topic','title':'Request {{name}}','text':'Follow up'}
  with self.assertRaises(ValueError):definition([topic])
  nodes=[{'id':'name','kind':'input','variable':'name','input_type':'text','text':'Name?'},topic]
  self.assertEqual(definition(nodes),nodes)
  topic['status']='Unknown'
  with self.assertRaises(ValueError):definition(nodes)
  topic['status']='Open';topic['title']='x'*141
  with self.assertRaises(ValueError):definition(nodes)

 def test_choice_labels_preserve_stable_branch_values(self):
  node={'id':'consent','kind':'input','input_type':'choice','variable':'consent','text':'Continue?','choices':[{'label':'HAAN','value':'yes'},{'label':'NAHI','value':'no'}]}
  definition([node])
  self.assertEqual(parse_input(node,'HAAN'),'yes')
  self.assertEqual(parse_input(node,'no'),'no')
  self.assertEqual(parse_input({**node,'input_type':'multi_choice'},'1,NAHI'),['yes','no'])
  node['choices'][1]['label']='yes'
  with self.assertRaises(ValueError):definition([node])

 def test_explicit_next_routes_join_without_falling_through(self):
  nodes=[{'id':'answer','kind':'input','variable':'answer','input_type':'text','text':'Choose'},
   {'id':'branch','kind':'condition','variable':'answer','operator':'eq','value':'yes','then':'yes','otherwise':'no'},
   {'id':'yes','kind':'reply','text':'Yes','next':'done'},
   {'id':'no','kind':'reply','text':'No'},
   {'id':'done','kind':'end','text':'Thank you'}]
  definition(nodes)
  nodes[2]['next']='answer'
  with self.assertRaises(ValueError):definition(nodes)

 def test_numbered_choices_reject_conflicting_numeric_aliases(self):
  node={'id':'rating','kind':'input','input_type':'multi_choice','variable':'rating','text':'Choose','choices':['2','1']}
  with self.assertRaises(ValueError):definition([node])
  with self.assertRaises(ValueError):parse_input(node,'1')
  node['choices']=['1','2']
  self.assertEqual(parse_input(node,'[" 2 ", "1"]'),['2','1'])
  node['input_type']='choice';node['choices']=['2','1']
  self.assertEqual(parse_input(node,'1'),'1')
