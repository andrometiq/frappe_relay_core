import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

class CallbackTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('inbound_test',Path('relay_core/inbound.py'))
        self.api=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,frappe=types.SimpleNamespace(whitelist=lambda **kw:lambda fn:fn)):
            spec.loader.exec_module(self.api)
        self.secret='s'*64
        self.raw=json.dumps({'account':'site-a','events':[{'id':1,'payload':{'entry':[]}}]}).encode()
    def sign(self,timestamp):
        return hmac.new(self.secret.encode(),str(timestamp).encode()+b'.'+self.raw,hashlib.sha256).hexdigest()
    def test_valid_callback(self):
        now=int(time.time())
        self.assertEqual(self.api.validate_callback(self.raw,str(now),self.sign(now),self.secret,'site-a')['events'][0]['id'],1)
    def test_replay_wrong_account_and_tamper_rejected(self):
        now=int(time.time())
        for raw,stamp,signature,account in [(self.raw,now-301,self.sign(now-301),'site-a'),(self.raw,now,self.sign(now),'other'),(self.raw+b' ',now,self.sign(now),'site-a')]:
            with self.assertRaises(ValueError):self.api.validate_callback(raw,str(stamp),signature,self.secret,account)

    def test_snapshot_conflict_retries_entire_callback_without_committing(self):
        class Conflict(Exception):
            pass
        db = Mock()
        callback = Mock(side_effect=[Conflict(1020), {'accepted': 500}])
        with patch.object(self.api, 'frappe', types.SimpleNamespace(db=db, QueryDeadlockError=Conflict)), \
                patch.object(self.api.time, 'sleep'):
            result = self.api.retry_callback(callback)()
        self.assertEqual(result, {'accepted': 500})
        self.assertEqual(callback.call_count, 2)
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    def test_callback_retries_are_bounded_and_other_errors_propagate(self):
        class Conflict(Exception):
            pass
        for failure, attempts in ((Conflict(1213), 5), (ValueError('invalid signature'), 1)):
            db = Mock()
            callback = Mock(side_effect=failure)
            with patch.object(self.api, 'frappe', types.SimpleNamespace(db=db, QueryDeadlockError=Conflict)), \
                    patch.object(self.api.time, 'sleep'):
                with self.assertRaises(type(failure)):
                    self.api.retry_callback(callback)()
            self.assertEqual(callback.call_count, attempts)
            self.assertEqual(db.rollback.call_count, 5 if isinstance(failure, Conflict) else 0)
            db.commit.assert_not_called()

    def test_compact_status_boundaries_and_identity(self):
        now=int(time.time())
        row={'event_id':7,'position':0,'message_id':'wamid.x','recipient':'919000000055','status':'delivered','timestamp':100}
        def check(rows):
            self.raw=json.dumps({'account':'site-a','statuses':rows}).encode()
            return self.api.validate_status_callback(self.raw,str(now),self.sign(now),self.secret,'site-a')
        self.assertEqual(len(check([dict(row,position=i) for i in range(500)])['statuses']),500)
        group=dict(row,recipient='group-one',recipient_type='group',participant='919000000001')
        self.assertEqual(check([group])['statuses'][0],group)
        for values in ([dict(group,participant='')],[dict(group,participant='x'*201)],[dict(group,recipient_type='individual')],
                       [dict(row,participant='919000000001')],[dict(row,recipient_type='invented')],
                       [],[dict(row,position=i) for i in range(501)],[row,row],
                       [dict(row,timestamp=True)],[dict(row,event_id=True)],
                       [dict(row,status='invented')],[dict(row,recipient='')],
                       [dict(row,position=-1)]):
            with self.assertRaises(ValueError):check(values)

    def test_channel_status_contract(self):
        now=int(time.time())
        row={'id':1,'delivery_id':2,'request_key':'stable-key','operation':'telegram.message','state':'submitted','receipt':{'message_id':99,'chat_id':123},'occurred_at':'2026-09-24T10:00:00Z'}
        def check(rows,account='site-a'):
            self.raw=json.dumps({'account':account,'statuses':rows}).encode()
            return self.api.validate_channel_status_callback(self.raw,str(now),self.sign(now),self.secret,'site-a')
        self.assertEqual(len(check([dict(row,id=i+1) for i in range(500)])['statuses']),500)
        whatsapp=dict(row,operation='whatsapp.execute',receipt={'messages':[{'id':'wamid.fixture'}]})
        self.assertEqual(check([whatsapp])['statuses'][0],whatsapp)
        with self.assertRaises(ValueError):check([dict(whatsapp,receipt={'messages':[{'id':''}]})])
        with self.assertRaises(ValueError):check([dict(row,receipt={'messages':[{'id':'wamid.fixture'}]})])
        for rows in ([],[row]*2,[dict(row,id=True)],[dict(row,receipt={'secret':'bad'})],[dict(row,receipt={'sent':1})],[dict(row,occurred_at='2026-09-24')],[dict(row,state='read')],[dict(row,id=i+1) for i in range(501)]):
            with self.assertRaises(ValueError):check(rows)
        with self.assertRaises(ValueError):check([row],account='another-site')
