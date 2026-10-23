import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

class ReportMediaTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('report_media_test',Path('relay_core/report_media.py'))
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,frappe=types.SimpleNamespace(get_doc=lambda dt,name:{'name':name,'message_type':'photo'})):
            spec.loader.exec_module(self.module)
        self.rows=[{'message':str(i),'message_type':'photo'} for i in range(55)]

    def test_opt_in_and_count_bound(self):
        with patch.object(self.module,'image_preview',return_value=b'image') as fetch:
            previews,notes=self.module.collect(self.rows,False)
            self.assertFalse(previews);self.assertEqual(len(notes),55);fetch.assert_not_called()
            previews,notes=self.module.collect(self.rows,True)
            self.assertEqual((len(previews),len(notes),fetch.call_count),(50,5,50))

    def test_missing_media_and_total_bytes(self):
        with patch.object(self.module,'image_preview',side_effect=ValueError('expired')):
            previews,notes=self.module.collect(self.rows[:1],True)
            self.assertFalse(previews);self.assertIn('unavailable',notes['0'])
        with patch.object(self.module,'image_preview',return_value=b'x'*(1024*1024)) as fetch:
            previews,notes=self.module.collect(self.rows,True)
            self.assertEqual((len(previews),len(notes),fetch.call_count),(20,35,20))

    def test_email_inventory(self):
        values=self.module.inventory({'message_type':'text','message_data':{'email':{'attachments':[{'filename':'invoice.pdf'}]}}})
        self.assertEqual(values,[{'type':'document','name':'invoice.pdf'}])
