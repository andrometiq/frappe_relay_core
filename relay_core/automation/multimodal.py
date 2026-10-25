"""Explicitly opted-in, bounded source media; bytes never come from model URLs."""
import io
import json
import math
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request
import uuid
from urllib.error import HTTPError
from relay_core.automation.providers import ProviderError, NoRedirect

MAX_BYTES=4*1024*1024


def image_input(raw,mime):
    from PIL import Image
    if mime not in ('image/jpeg','image/png','image/webp') or not 1<=len(raw)<=MAX_BYTES:
        raise ValueError('Choose a supported image up to 4 MiB')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height>12000000 or Image.MIME.get(image.format)!=mime:
            raise ValueError('Image dimensions or type exceed limits')
        image.verify()
    return {'mime':mime,'data':raw}


def audio_extension(raw,mime):
    extensions={'audio/mpeg':'mp3','audio/mp4':'m4a','audio/ogg':'ogg','application/ogg':'ogg','audio/wav':'wav','audio/x-wav':'wav','audio/webm':'webm'}
    if mime not in extensions or not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:
        raise ValueError('Choose supported audio up to 4 MiB')
    if shutil.which('ffprobe') is None:
        # WhatsApp voice notes are Ogg Opus; their length is read without ffprobe.
        if extensions[mime]!='ogg':raise ValueError('Audio length cannot be checked on this server')
        duration=ogg_duration(raw)
        if not 0<duration<=300:raise ValueError('Audio must be readable and at most five minutes')
        return 'ogg'
    # A private seekable file is needed to determine Ogg/MP4 duration. Explicit
    # demuxers reject playlists; network protocols are disabled.
    try:
        demuxer={'mp3':'mp3','m4a':'mov','ogg':'ogg','wav':'wav','webm':'matroska'}[extensions[mime]]
        with tempfile.NamedTemporaryFile(prefix='relay-voice-',suffix='.'+extensions[mime]) as source:
            source.write(raw);source.flush()
            result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file',
                '-f',demuxer,'-show_entries','format=duration:stream=codec_type,duration','-of','json','-i',source.name],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,check=True)
        if len(result.stdout)>16384:raise ValueError()
        probe=json.loads(result.stdout)
        streams=probe.get('streams') or []
        if not streams or any(stream.get('codec_type')!='audio' for stream in streams):raise ValueError()
        durations=[float(value) for value in [probe.get('format',{}).get('duration')]+[stream.get('duration') for stream in streams] if value not in (None,'N/A')]
        if not durations or not all(math.isfinite(value) and 0<value<=300 for value in durations):raise ValueError()
    except (subprocess.SubprocessError,OSError,ValueError,TypeError):
        raise ValueError('Audio must be readable and at most five minutes') from None
    return extensions[mime]


def ogg_duration(raw):
    """Seconds of a single-stream Ogg Opus or Vorbis file, from its last page's granule position."""
    if raw[:4]!=b'OggS' or len(raw)<64:raise ValueError('Audio must be readable and at most five minutes')
    serial=raw[14:18];packet=raw[27+raw[26]:]
    if packet.startswith(b'OpusHead'):
        rate=48000;skip=struct.unpack_from('<H',packet,10)[0]
    elif packet.startswith(b'\x01vorbis'):
        rate=struct.unpack_from('<I',packet,12)[0];skip=0
    else:
        raise ValueError('Audio must be Ogg Opus or Vorbis')
    last=raw.rfind(b'OggS')
    if last<0 or len(raw)<last+27 or raw[last+14:last+18]!=serial or not rate:
        raise ValueError('Audio must be readable and at most five minutes')
    granule=struct.unpack_from('<q',raw,last+6)[0]
    return (granule-skip)/rate


def transcribe(model,key,raw,mime):
    if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,160}',model) or not isinstance(key,str) or not key.strip():
        raise ProviderError('Choose a transcription model and key')
    extension=audio_extension(raw,mime)
    boundary='relay-'+uuid.uuid4().hex
    prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.{extension}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode()
    request=urllib.request.Request('https://api.openai.com/v1/audio/transcriptions',
        data=prefix+raw+f'\r\n--{boundary}--\r\n'.encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:
            body=response.read(65537)
        if len(body)>65536:raise ValueError()
        text=json.loads(body).get('text')
        if not isinstance(text,str) or not 1<=len(text.strip())<=12000:raise ValueError()
        return text
    except HTTPError as error:
        error.close();raise ProviderError('Transcription could not be completed') from None
    except Exception:
        raise ProviderError('Transcription could not be completed') from None


def context(policy,message,run):
    import frappe
    kind=message.message_type
    if kind in ('',None,'text'):return (message.content or '')[:12000],None
    if kind in ('voice','audio') and policy.get('allow_voice'):
        from relay_core.translations import source_text
        text,_=source_text(message,policy,run=run)
        return text,None
    from relay_core.attachments import read
    # The same account/endpoint/business checks used by private browser downloads
    # run before fetching source bytes. No arbitrary source file or URL is accepted.
    response=read(message.name)
    raw=response.get_data();mime=response.mimetype
    if kind in ('photo','image') and policy.get('allow_images'):
        return (message.content or '')[:12000],[image_input(raw,mime)]
    raise ValueError('This media type is not enabled for the policy')
