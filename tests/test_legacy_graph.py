import unittest
from relay_core.flows.legacy_graph import convert

class LegacyGraph(unittest.TestCase):
 def graph(self):
  return {'schema_version':1,'triggers':[{'type':'command','match':'/test'}], 'nodes':[
   {'id':'start','type':'start'},
   {'id':'ask','type':'ask_input','config':{'message':'Continue?','answer_key':'answer','input_type':'radio','options':[{'label':'HAAN','value':'yes'},{'label':'NAHI','value':'no'}]}},
   {'id':'branch','type':'condition'},
   {'id':'yes','type':'end','config':{'message':'Thank you'}},
   {'id':'no','type':'end','config':{'message':'Goodbye'}}],
   'edges':[{'source':'start','target':'ask'},{'source':'ask','target':'branch'},
    {'source':'branch','target':'yes','when':{'op':'eq','left':{'var':'answers.answer'},'right':'yes'}},
    {'source':'branch','target':'no','default':True}]}
 def test_conversion_preserves_choices_branches_and_final_messages(self):
  result=convert(self.graph());self.assertFalse(result['enabled']);self.assertTrue(result['requires_review'])
  self.assertEqual(result['nodes'][0]['choices'][0],{'label':'HAAN','value':'yes'})
  branch=next(n for n in result['nodes'] if n['kind']=='condition');self.assertEqual(branch['variable'],'answer')
  self.assertEqual(next(n for n in result['nodes'] if n['id']=='yes')['text'],'Thank you')
 def test_unknown_nodes_cycles_and_missing_defaults_reject(self):
  graph=self.graph();graph['nodes'][1]['type']='python'
  with self.assertRaises(ValueError):convert(graph)
  graph=self.graph();graph['edges'][-1].pop('default')
  with self.assertRaises(ValueError):convert(graph)

 def test_optional_input_and_unknown_config(self):
  graph=self.graph();graph['nodes'][1]['config']['required']=False
  self.assertTrue(convert(graph)['nodes'][0]['optional'])
  graph['nodes'][1]['config']['validation_regex']='.*'
  with self.assertRaises(ValueError):convert(graph)
