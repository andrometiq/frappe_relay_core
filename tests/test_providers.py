import unittest

from relay_core.automation.providers import ProviderError, extract, request_spec


class ProviderContractTests(unittest.TestCase):
    def test_supported_provider_hosts_and_auth_shapes(self):
        cases = [
            ('OpenRouter', 'openrouter.ai', 'Authorization'),
            ('Anthropic', 'api.anthropic.com', 'x-api-key'),
            ('GLM', 'api.z.ai', 'x-api-key'),
            ('Gemini', 'generativelanguage.googleapis.com', 'x-goog-api-key'),
        ]
        for provider, host, header in cases:
            url, headers, body = request_spec(provider, 'model-1', 'secret', 'prompt')
            self.assertEqual(host, url.split('/')[2])
            expected = 'Bearer secret' if provider == 'OpenRouter' else 'secret'
            self.assertEqual(expected, headers[header])
            self.assertTrue(body)

    def test_gemini_rejects_path_in_model(self):
        with self.assertRaises(ProviderError):
            request_spec('Gemini', 'models/foo', 'secret', 'prompt')

    def test_empty_key_is_rejected_before_network(self):
        with self.assertRaises(ProviderError):
            request_spec('OpenRouter', 'model-1', ' ', 'prompt')

    def test_extract_requires_complete_provider_response(self):
        with self.assertRaises(ProviderError):
            extract('OpenRouter', {'choices': [{'finish_reason': 'length'}]})
        with self.assertRaises(ProviderError):
            extract('Anthropic', {'stop_reason': 'max_tokens', 'content': []})
        with self.assertRaises(ProviderError):
            extract('Gemini', {'candidates': [{'finishReason': 'MAX_TOKENS'}]})


if __name__ == '__main__':
    unittest.main()
