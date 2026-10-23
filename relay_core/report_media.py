"""Bounded image previews and media inventory for prepared communication reports."""
from io import BytesIO
import json
import frappe

IMAGE_KINDS = {'image','photo','sticker'}

def inventory(message):
    data=message.get('message_data') or {}
    if isinstance(data,str):data=json.loads(data)
    media=data.get('media') or {}
    items=[]
    if message.get('message_type') in {'image','photo','video','audio','voice','document','animation','sticker','video_note'}:
        items.append({'type':message.get('message_type'),'name':str(media.get('file_name') or media.get('filename') or message.get('message_type'))[:200]})
    for item in (data.get('email') or {}).get('attachments',[])[:8]:
        items.append({'type':'document','name':str(item.get('filename') or item.get('file_name') or 'Email attachment')[:200]})
    return items


def image_preview(message):
    """Use the same permission-checked attachment route as the chat viewer."""
    from relay_core.attachments import read
    from relay_core.messaging import sticker
    from PIL import Image
    response=sticker(message['name']) if message.get('message_type')=='sticker' else read(message['name'])
    raw=response.get_data()
    if len(raw)>4*1024*1024:raise ValueError('Image exceeds preview limit')
    with Image.open(BytesIO(raw)) as original:
        if original.width*original.height>10000000:raise ValueError('Image exceeds preview dimensions')
        original.seek(0)
        original.thumbnail((900,900))
        image=original.convert('RGB')
        output=BytesIO();image.save(output,format='JPEG',quality=80)
        return output.getvalue()


def collect(rows, enabled):
    previews={};notes={};total=0
    for row in rows:
        if row.get('message_type') not in IMAGE_KINDS:continue
        name=row['message']
        if not enabled:
            notes[name]='Image preview not requested';continue
        if len(previews)>=50 or total>=20*1024*1024:
            notes[name]='Image preview omitted: report preview limit reached';continue
        try:
            source=frappe.get_doc('Relay Message',name)
            raw=image_preview(source)
            if total+len(raw)>20*1024*1024:
                notes[name]='Image preview omitted: report preview limit reached';continue
            previews[name]=raw;total+=len(raw)
        except Exception:
            # A missing/expired attachment must not discard the text report.
            notes[name]='Image preview unavailable; open the original message to review its attachment'
    return previews,notes
