import unittest
from unittest.mock import patch
from relay_core.automation.contracts import action_key, canonical, validate_decision
from relay_core.automation.providers import request_spec, extract, complete, ProviderError


class AutomationContractTests(unittest.TestCase):
    def decision(self):
        return dict(category='Query', brief='Ledger request', create_ticket=True, reply='approved', handoff=False)

    def test_only_explicitly_allowed_actions(self):
        value=self.decision()
        self.assertEqual(validate_decision(value, {'approved'}, allow_ticket=True),value)
        with self.assertRaises(ValueError):validate_decision(value, {'approved'},allow_ticket=False)
        for change in ({'reply':'unapproved'},{'create_ticket':'true'},{'handoff':1},{'category':'Execute SQL'},{'brief':''},{'tools':['run_method']}):
            with self.assertRaises(ValueError):validate_decision(value|change,{'approved'},allow_ticket=True)

    def test_stable_action_ids_ignore_model_output_and_distinguish_actions(self):
        self.assertEqual(action_key('message1','ticket'),action_key('message1','ticket'))
        self.assertNotEqual(action_key('message1','ticket'),action_key('message1','reply'))
        self.assertNotEqual(action_key('message1','ticket'),action_key('message2','ticket'))
        self.assertEqual(canonical({'b':2,'a':1}),canonical({'a':1,'b':2}))

    def test_provider_hosts_and_credentials_stay_out_of_body(self):
        for provider in ('OpenRouter','Anthropic','Gemini','GLM','OpenAI'):
            url,headers,body=request_spec(provider,'model','secret','தமிழ்')
            self.assertTrue(url.startswith('https://'))
            self.assertNotIn('secret',canonical(body))
            self.assertNotIn('secret',url)
        with self.assertRaises(ProviderError):request_spec('Gemini','../../attack','key','text')
        with self.assertRaises(ProviderError):request_spec('arbitrary','model','key','text')

    def test_truncated_responses_cannot_execute(self):
        with self.assertRaises(ProviderError):extract('Anthropic',{'stop_reason':'max_tokens','content':[]})
        with self.assertRaises(ProviderError):extract('OpenRouter',{'choices':[{'finish_reason':'length'}]})
        self.assertEqual(extract('Gemini',{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'secret reasoning','thought':True},{'text':'{}'}]}}]}),'{}')

    def test_provider_errors_redacted_and_limits_enforced(self):
        with patch('urllib.request.build_opener',side_effect=RuntimeError('secret credential')):
            with self.assertRaises(ProviderError) as e:complete('OpenRouter','model','secret','message')
            self.assertNotIn('secret',str(e.exception))
        with self.assertRaises(ProviderError):complete('OpenRouter','model','secret','x'*48001)


    def test_openai_responses_ignore_reasoning_and_reject_partial_or_refused_output(self):
        url,headers,body=request_spec('OpenAI','configured-model','secret','Return JSON')
        self.assertEqual(url,'https://api.openai.com/v1/responses')
        self.assertFalse(body['store'])
        self.assertEqual(body['max_output_tokens'],1500)
        response={'status':'completed','output':[{'type':'reasoning','summary':[]},{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"category":"Query"}'}]}]}
        self.assertEqual(extract('OpenAI',response),' {"category":"Query"}'.strip())
        for status in ('incomplete','failed','in_progress'):
            with self.assertRaises(ProviderError):extract('OpenAI',dict(response,status=status))
        with self.assertRaises(ProviderError):extract('OpenAI',{'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'declined'}]}]})
