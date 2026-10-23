import unittest
from relay_core.message_types import normalize

class TemplateButton(unittest.TestCase):
 def test_payload_is_distinct_from_display_text(self):
  result=normalize('button',{'text':'Give feedback','payload':'retailer_feedback_start'},provider='WhatsApp')
  self.assertEqual(result,{'kind':'text','text':'Give feedback','selection_id':'retailer_feedback_start','selection_type':'template_button'})
 def test_rejects_invalid_button_shape(self):
  with self.assertRaises(ValueError):normalize('button','not an object',provider='WhatsApp')
  with self.assertRaises(ValueError):normalize('button',{'payload':'x'*1001},provider='WhatsApp')
