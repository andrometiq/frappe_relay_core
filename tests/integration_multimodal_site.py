"""Current text-only skill boundary and permission-scoped historical transcripts."""
import json
import os
import sys
from unittest.mock import patch


def main():
    from integration_ai_permissions_site import confine_writes
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING']='1'
    import frappe
    from channel_site_fixtures import init
    from channel_identity_fixtures import scenario, configured, endpoint
    from relay_core import message_derivatives, attachments
    from relay_core.automation import service, queue
    from relay_core.ai import adapter
    init(); f=scenario()
    try:
        with configured(f):
            binding=endpoint(f,'Telegram','9555000125')
            skill=frappe.get_doc(dict(doctype='Relay AI Skill',name='LOCAL-BE-MEDIA-'+f.stamp,title='Local media handoff',enabled=1,
                channel=binding.channel,business_doctype='Customer',run_as_user=f.actor,handoff_owner=f.actor,mode='Automatic',daily_limit=10,
                instructions='Read this customer only.',allowed_tools='[]'))
            skill.db_insert();frappe.db.commit();frappe.conf.relay_automation_enabled=1
            for index,kind in enumerate(('photo','voice')):
                source=frappe.get_doc(dict(doctype='Relay Message',relay_contact=f.contact.name,channel=binding.channel,
                    direction='Incoming',content='Local media quantity 25',message_type=kind,sender_endpoint=binding.endpoint,
                    business_doctype='Customer',business_name=f.customer.name,
                    provider_context=json.dumps({'provider':'Telegram','chat_type':'private','chat_id':int(binding.endpoint),'message_id':100+index}),
                    message_data=json.dumps({'kind':kind,'media':{'file_id':'local-only'}}))).insert()
                queue._process(source.name);frappe.db.commit()
                name=frappe.db.get_value('Relay Automation Run',{'message':source.name},'name');assert name
                with patch.object(adapter,'complete') as model,patch.object(attachments,'read') as download:
                    service.process(name);service.process(name)
                    model.assert_not_called();download.assert_not_called()
                run=frappe.get_doc('Relay Automation Run',name)
                assert run.status=='Handoff' and run.ticket
                ticket=frappe.get_doc('Relay Ticket',run.ticket)
                assert ticket.assigned_to==f.actor and ticket.business_name==f.customer.name
                if kind=='voice':
                    # Older transcripts remain readable only through their source message.
                    run.transcript='Local historical quantity 25'
                    run.transcript_metadata=json.dumps({'model':'local-no-network','source_hash':service.message_hash(source)})
                    service.internal_save(run);frappe.db.commit();frappe.set_user(f.actor)
                    assert message_derivatives.transcript(source.name)['text']==run.transcript
                    frappe.set_user('Administrator')
                    frappe.db.set_value('Relay Message',source.name,{'business_doctype':'Supplier','business_name':f.supplier.name})
                    frappe.db.commit();frappe.set_user(f.actor)
                    try:message_derivatives.transcript(source.name)
                    except frappe.PermissionError:pass
                    else:raise AssertionError('Transcript crossed business scope')
                    frappe.set_user('Administrator')
                service.takeover(f.contact.name,0);frappe.db.commit()
            frappe.db.set_value('Relay AI Skill',skill.name,'enabled',0);frappe.db.commit()
            print('PASS unsupported media creates one assigned business handoff without model/download; historical transcript denies other business')
    finally:
        from channel_identity_fixtures import cleanup
        cleanup(f)
        frappe.destroy()


if __name__=='__main__':main()
