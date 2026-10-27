"""Business filters remain inside the permission-aware query for every channel."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from relay_core import business_inbox, inbox


class ChannelQueryTests(unittest.TestCase):
    def test_directory_preview_uses_original_text_and_decodes_legacy_html_once(self):
        import json
        text = 'Local & team <img src=x onerror=alert(1)> &amp; literal'
        self.assertEqual(inbox.directory_preview({'content':'Local &amp; team',
            'message_data':json.dumps({'kind':'text','text':text})}), text)
        self.assertEqual(inbox.directory_preview({'content':'<p>Local &amp; team &amp;amp; literal</p>'}),
            'Local & team &amp; literal')
        self.assertEqual(inbox.directory_preview({'message_data':{'kind':'text','text':'x'*250}}), 'x'*200)
        self.assertEqual(inbox.directory_preview({}), '')

    def test_business_timeline_accepts_three_providers_and_rejects_unknown(self):
        fake=Mock(); query=Mock(); query.where.return_value=query; query.run.return_value=[]
        fake.qb.DocType.side_effect=lambda name: __import__('pypika').Table(name)
        fake.qb.from_.side_effect=__import__('pypika').Query.from_
        with patch.object(business_inbox,'frappe',fake), patch.object(business_inbox,'check_type'), \
                patch.object(business_inbox,'resolved_contacts',return_value=[]), \
                patch.dict('sys.modules',{'relay_core.timeline':SimpleNamespace(page_query=Mock(return_value=query))}):
            for medium in (None,'WhatsApp','Telegram','Email'):
                result=business_inbox.messages('Customer','local',medium=medium)
                self.assertEqual(result['items'],[])
                self.assertEqual(result['ingestion_cursor'],'RELAY-MSG-0000000000')
            fake.throw.side_effect=ValueError
            with self.assertRaises(ValueError):business_inbox.messages('Customer','local',medium='SMS')
            fake.get_doc.return_value.check_permission.side_effect=PermissionError
            with self.assertRaises(PermissionError):business_inbox.messages('Supplier','hidden',medium='Email')

    def test_directory_channel_filter_rejects_unknown_before_execution(self):
        fake=Mock();fake.throw.side_effect=ValueError
        from relay_core import inbox_filters
        with patch.object(inbox,'frappe',fake), patch.object(inbox_filters,'frappe',fake), patch.object(inbox,'require_access'):
            with self.assertRaises(ValueError):inbox.directory(medium='SMS')
            fake.qb.get_query.assert_not_called()

    def test_business_pending_query_is_owner_scoped_before_pagination(self):
        from relay_core import messaging
        from pypika import Table, Query
        from pypika.queries import QueryBuilder
        statements=[]
        fake=Mock();fake.session.user='local-user'
        fake.qb=SimpleNamespace(DocType=Table,from_=Query.from_)
        def run(query, **kwargs):
            statements.append(query.get_sql());return []
        with patch.object(messaging,'frappe',fake), patch.object(messaging,'require_access'), patch.object(business_inbox,'check_type'), patch.object(QueryBuilder,'run',run,create=True):
            result=messaging.pending_messages(business_doctype='Customer',business_name='local')
            self.assertEqual(result,{'items':[],'next':None})
            self.assertIn('JSON_EXTRACT',statements[0])
            self.assertIn("'local-user'",statements[0]);self.assertIn("'local'",statements[0])
            self.assertTrue(statements[0].endswith('LIMIT 51'))
            fake.get_doc.return_value.check_permission.side_effect=PermissionError
            with self.assertRaises(PermissionError):messaging.pending_messages(business_doctype='Supplier',business_name='hidden')
            self.assertEqual(len(statements),1)
