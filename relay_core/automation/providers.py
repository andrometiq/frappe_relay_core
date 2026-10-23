"""Bounded API adapters. Fixed provider hosts; credentials never enter prompts."""
import json
import base64
import re
import urllib.request
from urllib.error import HTTPError


class ProviderError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('Provider redirect rejected')


def request_spec(provider, model, key, prompt, images=None):
    if not isinstance(key, str) or not key.strip():
        raise ProviderError('Provider key is required')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,160}', model):
        raise ProviderError('Invalid model identifier')
    headers = {'Content-Type': 'application/json'}
    if provider == 'OpenAI':
        url = 'https://api.openai.com/v1/responses'
        headers['Authorization'] = 'Bearer ' + key
        body = {'model': model, 'input': prompt, 'max_output_tokens': 1500, 'store': False,
                'text': {'format': {'type': 'json_object'}}}
    elif provider == 'OpenRouter':
        url = 'https://openrouter.ai/api/v1/chat/completions'
        headers['Authorization'] = 'Bearer ' + key
        body = {'model': model, 'max_tokens': 1500, 'messages': [{'role': 'user', 'content': prompt}]}
    elif provider in ('Anthropic', 'GLM'):
        url = 'https://api.anthropic.com/v1/messages' if provider == 'Anthropic' else 'https://api.z.ai/api/anthropic/v1/messages'
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        body = {'model': model, 'max_tokens': 1500, 'messages': [{'role': 'user', 'content': prompt}]}
        if provider == 'GLM':
            if model.startswith('glm-5.3'):
                url='https://api.z.ai/api/coding/paas/v4/chat/completions'
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key}
                body['thinking']={'type':'enabled'}
                body['reasoning_effort']='high'
                body['max_tokens']=8000
            else:
                body['thinking'] = {'type': 'disabled'}
    elif provider == 'Gemini':
        if '/' in model or ':' in model:
            raise ProviderError('Use a Gemini model identifier without a path')
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        headers['x-goog-api-key'] = key
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'maxOutputTokens': 1500, 'responseMimeType': 'application/json'}}
    else:
        raise ProviderError('Unsupported provider')
    if images:
        if not isinstance(images,list) or len(images)>1:
            raise ProviderError('One bounded source image is supported')
        image=images[0]
        if not isinstance(image,dict) or set(image)!={'mime','data'} or image['mime'] not in ('image/jpeg','image/png','image/webp'):
            raise ProviderError('Unsupported image input')
        raw=image['data']
        if not isinstance(raw,bytes) or not 1<=len(raw)<=4*1024*1024:
            raise ProviderError('Image exceeds limit')
        encoded=base64.b64encode(raw).decode()
        data_url='data:'+image['mime']+';base64,'+encoded
        if provider=='OpenAI':
            body['input']=[{'role':'user','content':[{'type':'input_text','text':prompt},{'type':'input_image','image_url':data_url}]}]
        elif provider=='Anthropic':
            body['messages'][0]['content']=[{'type':'image','source':{'type':'base64','media_type':image['mime'],'data':encoded}},{'type':'text','text':prompt}]
        elif provider=='Gemini':
            body['contents'][0]['parts'].append({'inlineData':{'mimeType':image['mime'],'data':encoded}})
        else:
            if provider=='GLM':
                url='https://api.z.ai/api/paas/v4/chat/completions'
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key}
            body['messages'][0]['content']=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':data_url}}]
    return url, headers, body


def extract(provider, response):
    if provider == 'OpenAI':
        if response.get('status') != 'completed':
            raise ProviderError('Incomplete model response')
        texts=[]
        for item in response.get('output', []):
            if item.get('type') != 'message' or item.get('role') != 'assistant':
                continue
            for block in item.get('content', []):
                if block.get('type') == 'refusal':
                    raise ProviderError('Model declined the request')
                if block.get('type') == 'output_text':
                    texts.append(block['text'])
        if not texts:
            raise ProviderError('No model text returned')
        return ''.join(texts)
    if provider == 'OpenRouter' or provider=='GLM' and 'choices' in response:
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ProviderError('Incomplete model response')
        return choice['message']['content']
    if provider in ('Anthropic', 'GLM'):
        if response.get('stop_reason') != 'end_turn':
            raise ProviderError('Incomplete model response')
        return ''.join(block['text'] for block in response['content'] if block['type'] == 'text')
    candidate = response['candidates'][0]
    if candidate.get('finishReason') != 'STOP':
        raise ProviderError('Incomplete model response')
    return ''.join(p['text'] for p in candidate['content']['parts'] if 'text' in p and not p.get('thought'))


def complete(provider, model, key, prompt, images=None):
    if not isinstance(prompt, str) or len(prompt.encode()) > 48000:
        raise ProviderError('Model context exceeds limit')
    try:
        url, headers, body = request_spec(provider, model, key, prompt, images)
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ProviderError('Provider response exceeds limit')
        text = extract(provider, json.loads(raw))
        if not isinstance(text, str) or len(text) > 12000:
            raise ProviderError('Invalid provider response')
        return json.loads(text)
    except HTTPError as exc:
        exc.close()
        raise ProviderError('AI provider could not return a valid decision') from None
    except Exception:
        # Provider bodies/errors can contain credentials or user data.
        raise ProviderError('AI provider could not return a valid decision') from None
