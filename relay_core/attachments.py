"""Private, bounded media bound to a permission-checked source conversation."""
import base64
import binascii
import os
import re
import frappe
from frappe.utils import get_datetime, now_datetime
from relay_core import file_limits, messaging, whatsapp
from relay_core.hub import MAX_WHATSAPP_DOWNLOAD_BYTES, HubError
from relay_core.hub_channels import hub_arguments

MEDIA_KINDS=('photo','image','video','audio','voice','document','animation')
# Meta keeps received media for about 30 days; after that the media ID no longer resolves.
WHATSAPP_MEDIA_DAYS=30


class MediaGone(frappe.ValidationError):
    http_status_code=410


class MediaRetry(frappe.ValidationError):
    http_status_code=503


def whatsapp_media(source,channel,media_id):
    """Download received WhatsApp media and turn Hub rejections into readable reasons."""
    try:return whatsapp.client().call_tool('whatsapp.attachment',hub_arguments(channel,{'media_id':media_id}))
    except HubError as error:check=error.metadata.get('error',{}).get('check')
    age=now_datetime()-get_datetime(source.sent_at or source.creation)
    if check=='provider_metadata' and age.days>=WHATSAPP_MEDIA_DAYS or check=='ownership':
        frappe.throw('Media no longer available from WhatsApp',MediaGone)
    if check=='size':frappe.throw('Media is larger than the 16 MiB download limit',MediaGone)
    if check=='capacity':frappe.throw('Media downloads are busy. Try again shortly.',MediaRetry)
    frappe.throw('WhatsApp did not return this media. Try again.',MediaRetry)


def template_media(data):
    """The image, video or document a template header sent, as its send parameter."""
    for component in (data.get('template') or {}).get('components') or []:
        if str(component.get('type')).lower()!='header':continue
        for parameter in component.get('parameters') or []:
            kind=parameter.get('type')
            if kind in ('image','video','document') and isinstance(parameter.get(kind),dict):return parameter[kind]
    return None


def file_content(name,source):
    """A private file kept on the source message. The caller has checked the source, so File's
    owner-only sharing rule does not apply."""
    from relay_core.business_access import document_name
    document_name(name)
    file=frappe.get_doc('File',name)
    if not file.is_private or file.attached_to_doctype!='Relay Message' or file.attached_to_name!=source.name:
        frappe.throw('Attachment belongs to another conversation source',frappe.PermissionError)
    raw=file.get_content()
    if isinstance(raw,str):raw=raw.encode()
    if error:=file_limits.size_error(len(raw),file_limits.get_max_bytes(),'The attachment'):frappe.throw(error)
    return file,raw


@frappe.whitelist(methods=['POST'])
def upload(message,filename,content_base64):
    source,channel,_=messaging.readable_source(message)
    if channel.channel not in ('Telegram','Email','WhatsApp'):frappe.throw('This channel does not support attachments')
    if not isinstance(filename,str) or not 1<=len(filename)<=120 or any(ord(c)<32 for c in filename) or any(c in filename for c in ('/','\\','"')):
        frappe.throw('Use a plain attachment filename of at most 120 characters')
    limit=file_limits.get_max_bytes()
    if not isinstance(content_base64,str) or len(content_base64)>file_limits.encoded_length(limit):frappe.throw(f'The attachment must be at most {file_limits.size_label(limit)}')
    try:raw=base64.b64decode(content_base64,validate=True)
    except (ValueError,binascii.Error):frappe.throw('Invalid attachment data')
    if error:=file_limits.size_error(len(raw),limit,'The attachment'):frappe.throw(error)
    from frappe.utils.file_manager import save_file
    file=save_file(filename,raw,'Relay Message',source.name,is_private=1)
    return {'name':file.name,'filename':file.file_name,'size':len(raw)}


def response(raw,mime,filename,download):
    from werkzeug.wrappers import Response
    # Never render active formats on the site's origin. PDF embeds are sandboxed
    # in the UI and get a restrictive response policy as a second boundary.
    safe={'image/jpeg','image/png','image/webp','image/gif','video/mp4','video/webm','audio/mpeg','audio/mp4','audio/ogg','audio/wav','application/ogg','application/pdf'}
    mime=mime.split(';')[0]
    inline=mime in safe and str(download)!='1'
    filename=re.sub(r'[^A-Za-z0-9._-]','_',filename or 'attachment')[:120]
    return Response(raw,content_type=mime if mime in safe else 'application/octet-stream',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox",'Content-Disposition':('inline' if inline else 'attachment')+'; filename="'+filename+'"'})


def archived_attachment(message,download=0):
    from relay_core.permissions import require_access, readable_contact
    require_access();messaging.validate_reference(message,'MSG')
    source=frappe.get_doc('Relay Message',message);source.check_permission('read')
    if source.get('legacy_triage'): require_access(configure=True)
    else: readable_contact(source.relay_contact)
    frappe.get_doc('Relay Channel',source.channel).check_permission('read')
    if not source.get('legacy_source'):return None
    data=messaging.object_value(source.message_data or {})
    if not data.get('attachment') or data.get('attachment_source')!=source.name:
        frappe.throw('This historical attachment was not available locally during import')
    file=frappe.get_doc('File',data['attachment'])
    if not file.is_private or file.attached_to_doctype!='Relay Message' or file.attached_to_name!=source.name:
        frappe.throw('Attachment belongs to another conversation source',frappe.PermissionError)
    if str(file.file_url).startswith(('/private/files/', '/files/')) and not os.path.isfile(file.get_full_path()):
        frappe.throw('This historical attachment was not copied to this site', frappe.DoesNotExistError)
    from relay_core.legacy_media import source_file, CHUNK
    def chunks():
        with source_file(file, source_checked=True) as stream:
            while chunk := stream.read(CHUNK):
                yield chunk
    import mimetypes
    return response(chunks(),mimetypes.guess_type(file.file_name)[0] or 'application/octet-stream',file.file_name,download)


@frappe.whitelist(methods=['GET'])
def read(message,download=0,index=None):
    if frappe.db.get_value('Relay Message',message,'legacy_source'):
        return archived_attachment(message,download)
    source,channel,_=messaging.readable_source(message)
    data=messaging.object_value(source.message_data or {})
    if channel.channel=='Email' and index is not None:
        metadata=(data.get('email') or {}).get('attachments') or []
        if isinstance(index,bool) or not str(index).isdigit() or not 0<=int(index)<len(metadata) or int(index)>=8:frappe.throw('Invalid attachment index')
        local=(data.get('email') or {}).get('local_attachments') or []
        if local:
            original,original_channel,_=messaging.readable_source(data['email'].get('attachment_source'))
            if original.relay_contact!=source.relay_contact or original_channel.name!=channel.name:frappe.throw('Attachment is not accessible',frappe.PermissionError)
            file,raw=file_content(local[int(index)],original)
            import mimetypes
            return response(raw,mimetypes.guess_type(file.file_name)[0] or 'application/octet-stream',file.file_name,download)
        result=whatsapp.client().call_tool('email.attachment',hub_arguments(channel,{'provider_id':source.provider_id,'index':int(index)}))
        try:raw=base64.b64decode(result.get('content_base64',''),validate=True)
        except (ValueError,binascii.Error,TypeError):frappe.throw('Invalid attachment response')
        if error:=file_limits.size_error(len(raw),file_limits.get_max_bytes(),'The attachment'):frappe.throw(error)
        return response(raw,result.get('content_type','application/octet-stream'),result.get('filename'),download)
    header=template_media(data)
    if source.message_type not in MEDIA_KINDS and not header and not (data.get('template') or {}).get('document'):
        frappe.throw('This message has no supported attachment')
    if data.get('attachment'):
        original,original_channel,_=messaging.readable_source(data.get('attachment_source'))
        if original.relay_contact!=source.relay_contact or original_channel.name!=channel.name:frappe.throw('Attachment is not accessible',frappe.PermissionError)
        file,raw=file_content(data['attachment'],original)
        import mimetypes
        return response(raw,mimetypes.guess_type(file.file_name)[0] or 'application/octet-stream',file.file_name,download)
    if channel.channel=='WhatsApp':
        media=data.get('media') or header or {};media_id=media.get('id')
        if not isinstance(media_id,str) or not re.fullmatch(r'[0-9]{1,100}',media_id):frappe.throw('Attachment reference is missing')
        result=whatsapp_media(source,channel,media_id)
        try:raw=base64.b64decode(result.get('content_base64',''),validate=True)
        except (ValueError,binascii.Error,TypeError):frappe.throw('Invalid attachment response')
        if not 1<=len(raw)<=MAX_WHATSAPP_DOWNLOAD_BYTES:frappe.throw('Attachment exceeds the 16 MiB download limit')
        return response(raw,result.get('content_type','application/octet-stream'),media.get('filename') or result.get('filename'),download)
    if channel.channel!='Telegram':frappe.throw('Remote attachment download is not available for this channel')
    media=data.get('media') or {};file_id=media.get('file_id')
    if not isinstance(file_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',file_id):frappe.throw('Attachment reference is missing')
    result=whatsapp.client().call_tool('telegram.attachment',hub_arguments(channel,{'file_id':file_id}))
    try:raw=base64.b64decode(result.get('content_base64',''),validate=True)
    except (ValueError,binascii.Error,TypeError):frappe.throw('Invalid attachment response')
    if error:=file_limits.size_error(len(raw),file_limits.get_max_bytes(),'The attachment'):frappe.throw(error)
    return response(raw,result.get('content_type','application/octet-stream'),media.get('file_name') or result.get('filename'),download)
