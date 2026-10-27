import types
import unittest
from unittest.mock import Mock

from test_ai_skills import Doc, framework, module


class PreparedReportHookTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.publish_realtime = Mock()
        inbox = types.SimpleNamespace(messages=Mock(), check_type=Mock())
        access = types.SimpleNamespace(require_access=Mock())
        self.reports = module('relay_core/prepared_reports.py', self.f,
                              {'relay_core.business_inbox': inbox, 'relay_core.permissions': access})

    def test_other_reports_and_their_files_need_no_document_load(self):
        report = Doc(report_name='Stock Balance', status='Completed', owner='someone')
        self.reports.notify(report)
        self.assertTrue(self.reports.permission(report))
        self.f.db.get_value.return_value = 'Stock Balance'
        self.assertTrue(self.reports.file_permission(Doc(attached_to_doctype='Prepared Report', attached_to_name='PR-1')))
        self.assertTrue(self.reports.file_permission(Doc(attached_to_doctype='Item', attached_to_name='ITEM-1')))
        self.f.db.get_value.assert_called_once_with('Prepared Report', 'PR-1', 'report_name')
        self.f.get_doc.assert_not_called()
        self.f.publish_realtime.assert_not_called()

    def test_file_of_a_deleted_report_does_not_raise(self):
        self.f.db.get_value.return_value = None
        self.assertTrue(self.reports.file_permission(Doc(attached_to_doctype='Prepared Report', attached_to_name='gone')))
        self.f.get_doc.assert_not_called()

    def test_relay_report_file_uses_report_permission(self):
        self.f.db.get_value.return_value = self.reports.REPORT
        report = Doc(report_name=self.reports.REPORT, owner='owner@example.com')
        self.f.get_doc.return_value = report
        self.f.session.user = 'other@example.com'
        self.assertFalse(self.reports.file_permission(Doc(attached_to_doctype='Prepared Report', attached_to_name='PR-2')))
        self.f.get_doc.assert_called_once_with('Prepared Report', 'PR-2')


if __name__ == '__main__':
    unittest.main()
