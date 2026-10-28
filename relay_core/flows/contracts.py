"""Bounded flow definitions and input parsing; no dynamic code or regex execution."""
import datetime
import json
import math
import re

KINDS={'input','reply','ticket','handoff','condition','wait','end','topic','action'}
TYPES={'text','number','email','date','choice','multi_choice','content'}
CONTENT_TYPES={'text','image','video','audio','voice','document','sticker','location','contact','contacts'}
FIELDS={'id','kind','text','variable','input_type','choices','category','operator','value','then','otherwise','seconds',
        'minimum','maximum','integer_only','optional','title','status','action','arguments','next',
        'min_length','max_length','error_text','accept','button','max_visits'}
NAME=r'[a-z][a-z0-9_]{0,39}'
# A reference is a collected input or an action result, optionally followed by result keys.
PATH=NAME+r'(?:\.[a-z0-9_]{1,40}){0,5}'
REFERENCE=re.compile(r'\{\{('+PATH+r')\}\}')
DEFAULT_VISITS=20
LAST_INPUT='last_input'


def root(path):
    return path.split('.',1)[0]


def lookup(values,path):
    """A collected value or a key inside an action result; missing keys read as None."""
    value=values
    for key in path.split('.'):
        if not isinstance(value,dict):return None
        value=value.get(key)
    return value


def produced(node):
    """Names a step sets. Every answer is also kept as last_input, the most recent reply."""
    if node['kind']=='input':return {node['variable'],LAST_INPUT}
    return {node['variable']} if node['kind']=='action' and node.get('variable') else set()


def successors(node,index,positions):
    if node['kind'] in ('end','handoff'):return []
    if node['kind']=='condition':return [positions[node['then']],positions[node['otherwise']]]
    return [positions[node['next']] if node.get('next') else index+1]


def references(node):
    found=set(REFERENCE.findall(node.get('text','')+' '+str(node.get('title',''))))
    if node['kind']=='condition':found.add(node['variable'])
    return {root(path) for path in found}


def check_node(node,seen):
    if not isinstance(node,dict) or set(node)-FIELDS:
        raise ValueError('Unsupported flow step fields')
    if not isinstance(node.get('id'),str) or not re.fullmatch(NAME,node['id']) or node['id'] in seen:
        raise ValueError('Every step needs a unique identifier')
    if node.get('kind') not in KINDS:raise ValueError('Unsupported flow step')
    if node['kind'] in ('condition','wait','end','action'):node.setdefault('text','')
    if not isinstance(node.get('text'),str) or len(node['text'])>2000 or (node['kind'] not in ('condition','wait','end','action') and not node['text'].strip()):
        raise ValueError('Step text must contain 1–2000 characters')
    if 'max_visits' in node and (type(node['max_visits']) is not int or not 1<=node['max_visits']<=100):
        raise ValueError('A step can repeat 1–100 times')
    if node['kind']=='input':check_input(node)
    if node['kind']=='condition':
        if not isinstance(node.get('variable'),str) or not re.fullmatch(PATH,node['variable']) or node.get('operator') not in ('eq','ne','contains','gt','gte','lt','lte','is_set'):
            raise ValueError('Choose a collected input and condition operator')
        if not isinstance(node.get('value',''),str) or len(node.get('value',''))>1000:raise ValueError('Invalid condition value')
    if node['kind']=='wait' and (type(node.get('seconds')) is not int or not 1<=node['seconds']<=86400):raise ValueError('Delay must be between 1 second and 24 hours')
    if node['kind']=='action':
        if not isinstance(node.get('action'),str) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,99}',node['action']):raise ValueError('Choose a registered business action')
        if not isinstance(node.get('arguments',{}),dict):raise ValueError('Business action arguments must be an object')
        if 'variable' in node and (not isinstance(node['variable'],str) or not re.fullmatch(NAME,node['variable'])):
            raise ValueError('Choose a valid result name')
    if node['kind']=='topic':
        if not isinstance(node.get('title'),str) or not 1<=len(node['title'].strip())<=140:raise ValueError('Topic title must contain 1–140 characters')
        if node.get('status','Open') not in ('Open','Waiting','Resolved','Archived'):raise ValueError('Unsupported topic status')
    # Ticket categories are configurable; saving an enabled flow checks them against Ticket settings.
    if node['kind'] in ('topic','ticket') and (not isinstance(node.get('category',''),str) or len(node.get('category',''))>140):
        raise ValueError(node['kind'].title()+' category is too long')


def check_input(node):
    name=node.get('variable')
    if not isinstance(name,str) or not re.fullmatch(NAME,name):
        raise ValueError('Choose a unique input variable')
    if node.get('input_type') not in TYPES:raise ValueError('Choose a supported input type')
    for option in ('integer_only','optional'):
        if option in node and type(node[option]) is not bool:raise ValueError('Input switches must be true or false')
    for bound in ('minimum','maximum'):
        if node.get(bound) is not None and (type(node[bound]) not in (int,float) or not math.isfinite(node[bound]) or abs(node[bound])>1e12):raise ValueError('Input bounds must be finite numbers within ±1 trillion')
    if node.get('minimum') is not None and node.get('maximum') is not None and node['minimum']>node['maximum']:raise ValueError('Minimum cannot exceed maximum')
    for bound in ('min_length','max_length'):
        if bound in node and (type(node[bound]) is not int or not 1<=node[bound]<=4096):raise ValueError('Text length limits must be 1–4096 characters')
    if node.get('min_length',1)>node.get('max_length',1000):raise ValueError('Minimum length cannot exceed maximum length')
    for key,limit in (('error_text',1000),('button',20)):
        if key in node and (not isinstance(node[key],str) or len(node[key])>limit):raise ValueError('Input labels are too long')
    if 'accept' in node and (not isinstance(node['accept'],list) or not node['accept'] or set(node['accept'])-CONTENT_TYPES):
        raise ValueError('Choose the message types this step accepts')
    if node['input_type'] in ('choice','multi_choice'):
        choice_options(node.get('choices'), numbered=node['input_type']=='multi_choice')


def check_paths(value):
    """Every step is reachable, uses only values collected on every path to it, and every loop waits for a reply."""
    positions={node['id']:index for index,node in enumerate(value)}
    for index,node in enumerate(value):
        for key in ('then','otherwise') if node['kind']=='condition' else ():
            if node.get(key) not in positions or positions[node[key]]==index:raise ValueError('Condition branches must point to other steps')
        if 'next' in node and (node['kind'] in ('condition','end','handoff') or not isinstance(node['next'],str) or node['next'] not in positions or positions[node['next']]==index):
            raise ValueError('Next step must point to another step')
    edges=[[target for target in successors(node,index,positions) if target<len(value)] for index,node in enumerate(value)]
    # Values available on entry: the intersection over every path, computed to a fixed point so loops are covered.
    available={0:frozenset()}
    pending=[0]
    while pending:
        index=pending.pop()
        leaving=available[index]|produced(value[index])
        for target in edges[index]:
            merged=leaving if target not in available else available[target]&leaving
            if merged!=available.get(target):
                available[target]=merged;pending.append(target)
    if len(available)!=len(value):raise ValueError('Every flow step must be reachable')
    for index,node in enumerate(value):
        guaranteed=available[index]
        if not references(node)<=guaranteed:raise ValueError('An input may be skipped before this step uses it')
        if node['kind']=='action':
            from relay_core.flows.action_contracts import resolve
            resolve(node.get('arguments',{}),{name:None for name in guaranteed})
    automatic(value,edges)


def automatic(value,edges):
    """A loop must stop for a reply or a delay, so one message can never spin a flow forever."""
    state={}
    def visit(index):
        state[index]=1
        for target in edges[index]:
            if value[target]['kind'] in ('input','wait'):continue
            if state.get(target)==1:raise ValueError('A loop must wait for a reply')
            if target not in state:visit(target)
        state[index]=2
    for index,node in enumerate(value):
        if index not in state and node['kind'] not in ('input','wait'):visit(index)


def definition(value):
    if isinstance(value,str):
        if len(value)>50000:raise ValueError('Flow definition exceeds 50,000 characters')
        value=json.loads(value)
    if not isinstance(value,list) or not 1<=len(value)<=30:raise ValueError('Choose between 1 and 30 flow steps')
    seen=set()
    for node in value:
        check_node(node,seen)
        seen.add(node['id'])
    check_paths(value)
    return value


def text_value(value):
    if isinstance(value,bool):return 'true' if value else 'false'
    return '' if value is None else str(value)


def matches(node,values):
    original=lookup(values,node['variable'])
    actual=text_value(original);expected=node.get('value','');operator=node['operator']
    if operator=='is_set':return bool(actual.strip())
    if operator=='eq':return actual.casefold()==expected.casefold()
    if operator=='ne':return actual.casefold()!=expected.casefold()
    if operator=='contains':
        if isinstance(original,list):return any(str(item).casefold()==expected.casefold() for item in original)
        return expected.casefold() in actual.casefold()
    try:left=float(actual);right=float(expected)
    except (ValueError,TypeError):return False
    if not math.isfinite(left) or not math.isfinite(right):return False
    return {'gt':left>right,'gte':left>=right,'lt':left<right,'lte':left<=right}[operator]


def parse_content(node,value,message):
    kind=(message or {}).get('message_type') or 'text'
    if kind not in node.get('accept',sorted(CONTENT_TYPES)):
        raise ValueError(node.get('error_text') or 'Send one of: '+', '.join(node.get('accept')))
    if kind=='text' and not (isinstance(value,str) and value.strip()):raise ValueError('Send a message')
    return {'type':kind,'text':(value or '')[:4000],'message':(message or {}).get('name')}


def parse_input(node,value,message=None):
    kind=node['input_type']
    if kind=='content':return parse_content(node,value,message)
    if (message or {}).get('message_type') not in (None,'','text'):raise ValueError(node.get('error_text') or 'Send a text message')
    limit=node.get('max_length',1000) if kind=='text' else 1000
    if not isinstance(value,str) or not 1<=len(value.strip())<=limit:raise ValueError(node.get('error_text') or 'Enter 1–{} characters'.format(limit))
    value=value.strip()
    if node.get('optional') and value.casefold()=='skip':return ''
    if kind=='text':
        if not node.get('min_length',1)<=len(value)<=node.get('max_length',1000):
            raise ValueError(node.get('error_text') or 'Enter {}–{} characters'.format(node.get('min_length',1),node.get('max_length',1000)))
    elif kind=='number':
        try:number=float(value)
        except ValueError:raise ValueError('Enter a number') from None
        if not math.isfinite(number) or abs(number)>1e12:raise ValueError('Enter a finite number within ±1 trillion')
        if node.get('integer_only') and not number.is_integer():raise ValueError('Enter a whole number')
        if node.get('minimum') is not None and number<node['minimum']:raise ValueError('Enter a number at least '+str(node['minimum']))
        if node.get('maximum') is not None and number>node['maximum']:raise ValueError('Enter a number at most '+str(node['maximum']))
    elif kind=='email':
        if not re.fullmatch(r'[^\s@<>]{1,64}@[^\s@<>]{1,190}\.[^\s@<>]{2,63}',value):raise ValueError('Enter a valid email address')
    elif kind=='date':
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
            datetime.date.fromisoformat(value)
        except ValueError:raise ValueError('Enter a date as YYYY-MM-DD') from None
    elif kind=='multi_choice':
        if value.startswith('['):
            try:items=json.loads(value)
            except ValueError:raise ValueError('Enter a list of choices') from None
        else:items=[item.strip() for item in value.split(',')]
        if not isinstance(items,list) or not 1<=len(items)<=20 or any(not isinstance(item,str) for item in items):raise ValueError('Select between 1 and 20 choices')
        options=choice_options(node['choices'], numbered=True)
        selected=[]
        for item in items:
            item=item.strip()
            match=next((choice['value'] for index,choice in enumerate(options) if item.casefold() in (choice['label'].casefold(),choice['value'].casefold()) or str(index+1)==item),None)
            if match is None:raise ValueError('Choose from the numbered options')
            if match not in selected:selected.append(match)
        return selected
    elif kind=='choice':
        options=choice_options(node['choices'])
        match=next((choice['value'] for choice in options if value.casefold() in (choice['label'].casefold(),choice['value'].casefold())),None)
        if match is None and value.isdigit() and 1<=int(value)<=len(options):match=options[int(value)-1]['value']
        if match is None:raise ValueError(node.get('error_text') or 'Choose: '+', '.join(choice['label'] for choice in options))
        value=match
    return value


def render(text,values):
    def value(match):
        found=lookup(values,match[1])
        return ', '.join(str(item) for item in found) if isinstance(found,list) else text_value(found)
    result=REFERENCE.sub(value,text)
    if len(result)>4000:raise ValueError('Rendered step exceeds 4000 characters')
    return result


def prompt(node,values):
    """The question text with its options; choices are numbered so a reply can be the number or the label."""
    text=render(node['text'],values)
    if node['input_type'] in ('choice','multi_choice'):
        text+='\n'+'\n'.join(str(index+1)+'. '+choice['label'] for index,choice in enumerate(choice_options(node['choices'])))
    if node['input_type']=='multi_choice':text+='\nReply with choice numbers separated by commas.'
    if node.get('optional'):text+='\nReply skip to leave this blank.'
    return text


def choice_options(choices, *, numbered=False):
    if not isinstance(choices,list) or not 1<=len(choices)<=20:
        raise ValueError('Choose 1–20 distinct input choices')
    result=[];aliases={}
    for index,choice in enumerate(choices):
        row={'label':choice,'value':choice} if isinstance(choice,str) else choice
        if not isinstance(row,dict) or set(row)!={'label','value'} or any(not isinstance(v,str) or not 1<=len(v.strip())<=80 for v in row.values()):
            raise ValueError('Choices need a label and value of 1–80 characters')
        for alias in {row['label'].casefold(),row['value'].casefold()}:
            if alias in aliases:raise ValueError('Choice labels and values must be unambiguous')
            aliases[alias]=index
        result.append(row)
    if numbered:
        for number in range(1,len(result)+1):
            if str(number) in aliases and aliases[str(number)] != number-1:
                raise ValueError('A choice label or value conflicts with another option number')
    return result
