import io,json,wave,unittest
from unittest.mock import patch
from PIL import Image
from relay_core.automation import providers,multimodal


def wav(seconds=1):
 b=io.BytesIO()
 with wave.open(b,'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(1000);out.writeframes(b'\0\0'*int(seconds*1000))
 return b.getvalue()

class MultimodalTests(unittest.TestCase):
 def test_all_provider_image_contracts_keep_bytes_inline(self):
  image={'mime':'image/png','data':b'fixture-image'}
  for provider in ('OpenAI','OpenRouter','Anthropic','Gemini','GLM'):
   url,headers,body=providers.request_spec(provider,'fixture-model','synthetic-secret','Return JSON',[image])
   self.assertIn('Zml4dHVyZS1pbWFnZQ==',json.dumps(body));self.assertNotIn('synthetic-secret',json.dumps(body));self.assertTrue(url.startswith('https://'))
  self.assertEqual(providers.request_spec('GLM','fixture-model','key','prompt',[image])[0],'https://api.z.ai/api/paas/v4/chat/completions')
  for image in ({'mime':'text/html','data':b'bad'},{'mime':'image/png','data':'https://invalid'}, {'mime':'image/png','data':b'x'*(4*1024*1024+1)}):
   with self.assertRaises(providers.ProviderError):providers.request_spec('OpenAI','model','key','prompt',[image])
 def test_corrupt_or_mislabeled_images_rejected(self):
  raw=io.BytesIO();Image.new('RGB',(10,10)).save(raw,format='PNG')
  self.assertEqual(multimodal.image_input(raw.getvalue(),'image/png')['mime'],'image/png')
  for data,mime in [(b'<script>bad</script>','image/png'),(raw.getvalue(),'image/jpeg')]:
   with self.assertRaises((ValueError,OSError)):multimodal.image_input(data,mime)
 def test_audio_duration_and_malformed_media(self):
  self.assertEqual(multimodal.audio_extension(wav(),'audio/wav'),'wav')
  for data in (wav(301),b'#EXTM3U\nhttps://example.invalid/private'):
   with self.assertRaises(ValueError):multimodal.audio_extension(data,'audio/wav')
 def test_transcription_fixed_host_bounded_json_and_redaction(self):
  class Reply:
   def __init__(self,body):self.body=body
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,limit):return self.body[:limit]
  with patch.object(multimodal.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=Reply(b'{"text":"Please help"}')
   self.assertEqual(multimodal.transcribe('fixture-transcribe','synthetic-secret',wav(),'audio/wav'),'Please help')
   request=opener.return_value.open.call_args.args[0]
   self.assertEqual(request.full_url,'https://api.openai.com/v1/audio/transcriptions');self.assertIn(b'filename="voice.wav"',request.data)
   opener.return_value.open.side_effect=RuntimeError('synthetic-secret')
   with self.assertRaises(providers.ProviderError) as error:multimodal.transcribe('fixture-transcribe','synthetic-secret',wav(),'audio/wav')
   self.assertNotIn('synthetic-secret',str(error.exception))


def ogg_page(serial,granule,packet,first=False):
 import struct
 return b'OggS'+bytes([0,2 if first else 0])+struct.pack('<qII',granule,serial,0)+b'\0\0\0\0'+bytes([1,len(packet)])+packet

def opus(seconds,serial=7):
 import struct
 head=b'OpusHead'+bytes([1,1])+struct.pack('<HIhB',312,48000,0,0)
 return ogg_page(serial,0,head,True)+ogg_page(serial,0,b'OpusTags'+b'\0'*8)+ogg_page(serial,312+int(seconds*48000),b'\0'*20)

class OggDurationTests(unittest.TestCase):
 def test_voice_note_length_without_ffprobe(self):
  self.assertAlmostEqual(multimodal.ogg_duration(opus(12.5)),12.5)
  with patch.object(multimodal.shutil,'which',return_value=None):
   self.assertEqual(multimodal.audio_extension(opus(12.5),'audio/ogg'),'ogg')
   for data in (opus(301),opus(0),b'OggS'+b'\0'*80,opus(5)[:-30]+ogg_page(9,10**9,b'\0'*4)):
    with self.assertRaises(ValueError):multimodal.audio_extension(data,'audio/ogg')
   # Other containers still need ffprobe to bound their length.
   with self.assertRaises(ValueError):multimodal.audio_extension(wav(),'audio/wav')
