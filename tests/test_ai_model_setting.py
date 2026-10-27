import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from relay_core import translations
from relay_core.automation import providers
from relay_core.learning import service as learning

MODEL = types.SimpleNamespace(name='Router', provider='OpenRouter', model_id='router/model', modified='2026-10-27', enabled=1)


def policy(**values):
    row = types.SimpleNamespace(name='Channel', ai_model='Router', **values)
    row.get = lambda key, default=None: getattr(row, key, default)
    return row


class TranslationModelTests(unittest.TestCase):
    def translate(self, result):
        fake = types.SimpleNamespace(get_doc=Mock(return_value=MODEL))
        complete = Mock(return_value=result)
        with patch.object(translations, 'frappe', fake), patch.object(translations, 'complete_with_fallback', complete):
            return translations._translate_part('Vanakkam', policy()), complete

    def test_translation_uses_the_policy_ai_model(self):
        row, complete = self.translate({'language': 'ta', 'text': 'Hello'})
        self.assertEqual(row, {'language': 'ta', 'text': 'Hello', 'target_language': 'en',
                               'provider': 'OpenRouter', 'model': 'router/model'})
        self.assertEqual(complete.call_count, 1)

    def test_translation_rejects_an_invalid_shape(self):
        with self.assertRaises(providers.ProviderError):
            self.translate({'language': 'ta'})


class LearnedProcedureModelTests(unittest.TestCase):
    def test_contract_hash_follows_the_ai_model(self):
        fake = types.SimpleNamespace(get_doc=Mock(return_value=MODEL), parse_json=lambda value: value)
        doc = types.SimpleNamespace(instructions='Help', examples=[{'message': 'hi', 'expected': {}}] * 3,
                                    policy='Channel', source_message=None)
        with patch.object(learning, 'frappe', fake):
            first = learning.hashes(doc, policy(allow_reply=0))
            MODEL.modified = '2026-10-28'
            try:
                second = learning.hashes(doc, policy(allow_reply=0))
            finally:
                MODEL.modified = '2026-10-27'
        self.assertEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])


class ProviderPatchTests(unittest.TestCase):
    def run_patch(self, policies, legacy, has_column=True):
        inserted, updated = [], []
        def get_doc(*args, **values):
            if args:
                return legacy[args[1]]
            return types.SimpleNamespace(insert=lambda **kwargs: inserted.append(values))
        db = types.SimpleNamespace(has_column=lambda *args: has_column,
                                   exists=lambda doctype, name: doctype == 'Relay AI Provider' and name in legacy,
                                   set_value=lambda *args, **kwargs: updated.append(args))
        fake = types.SimpleNamespace(db=db, get_all=lambda *args, **kwargs: policies, get_doc=get_doc)
        with patch.dict(sys.modules, frappe=fake):
            sys.modules.pop('relay_core.patches.v1_0.move_policy_providers_to_ai_model', None)
            importlib.import_module('relay_core.patches.v1_0.move_policy_providers_to_ai_model').execute()
        return inserted, updated

    def legacy(self, name, provider):
        return types.SimpleNamespace(name=name, provider=provider, model='m', enabled=1,
                                     get_password=lambda *args, **kwargs: 'synthetic-key')

    def test_patch_copies_a_supported_legacy_provider(self):
        legacy = {'Gem': self.legacy('Gem', 'Gemini'), 'Router': self.legacy('Router', 'OpenRouter')}
        rows = [types.SimpleNamespace(name='Channel', provider='Gem', fallback_provider='Router')]
        inserted, updated = self.run_patch(rows, legacy)
        self.assertEqual([row['doctype'] for row in inserted], ['AI Provider Account', 'AI Model'])
        self.assertEqual(inserted[1]['model_id'], 'm')
        self.assertEqual(updated, [('Relay Automation Policy', 'Channel', 'ai_model', 'Relay Router')])

    def test_patch_leaves_unsupported_providers_alone(self):
        rows = [types.SimpleNamespace(name='Channel', provider='Gem', fallback_provider=None)]
        with patch('builtins.print'):
            self.assertEqual(self.run_patch(rows, {'Gem': self.legacy('Gem', 'Gemini')}), ([], []))

    def test_patch_skips_sites_without_the_legacy_column(self):
        self.assertEqual(self.run_patch([], {}, has_column=False), ([], []))

    def test_patch_is_registered(self):
        self.assertIn('relay_core.patches.v1_0.move_policy_providers_to_ai_model',
                      Path('relay_core/patches.txt').read_text().split())
