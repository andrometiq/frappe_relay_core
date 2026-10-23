"""Bounded flow definitions and input parsing; no dynamic code or regex execution."""
import datetime
import json
import math
import re

KINDS={'input','reply','ticket','handoff','condition','wait','end','topic','action'}
TYPES={'text','number','email','date','choice','multi_choice'}


def definition(value):
    if isinstance(value,str):
        if len(value)>50000:raise ValueError('Flow definition exceeds 50,000 characters')
        value=json.loads(value)
    if not isinstance(value,list) or not 1<=len(value)<=30:raise ValueError('Choose between 1 and 30 flow steps')
    seen=set();variables=set()
    for node in value:
        if not isinstance(node,dict) or set(node)-{'id','kind','text','variable','input_type','choices','category','operator','value','then','otherwise','seconds','minimum','maximum','integer_only','optional','title','status','action','arguments','next'}:
            raise ValueError('Unsupported flow step fields')
        if not isinstance(node.get('id'),str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',node['id']) or node['id'] in seen:
            raise ValueError('Every step needs a unique identifier')
        seen.add(node['id'])
        if node.get('kind') not in KINDS:raise ValueError('Unsupported flow step')
        if node['kind'] in ('condition','wait','end','action'):node.setdefault('text','')
        if not isinstance(node.get('text'),str) or len(node['text'])>2000 or (node['kind'] not in ('condition','wait','end','action') and not node['text'].strip()):
            raise ValueError('Step text must contain 1–2000 characters')
        for variable in re.findall(r'\{\{([a-z][a-z0-9_]{0,39})\}\}',node['text']+' '+str(node.get('title',''))):
            if variable not in variables:raise ValueError('Step refers to an input that has not been collected')
        if node['kind']=='input':
            name=node.get('variable')
            if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',name) or name in variables:
                raise ValueError('Choose a unique input variable')
            variables.add(name)
            if node.get('input_type') not in TYPES:raise ValueError('Choose a supported input type')
            for option in ('integer_only','optional'):
                if option in node and type(node[option]) is not bool:raise ValueError('Input switches must be true or false')
            for bound in ('minimum','maximum'):
                if node.get(bound) is not None and (type(node[bound]) not in (int,float) or not math.isfinite(node[bound]) or abs(node[bound])>1e12):raise ValueError('Input bounds must be finite numbers within ±1 trillion')
            if node.get('minimum') is not None and node.get('maximum') is not None and node['minimum']>node['maximum']:raise ValueError('Minimum cannot exceed maximum')
            if node['input_type'] in ('choice','multi_choice'):
                choices=node.get('choices')
                choice_options(choices, numbered=node['input_type']=='multi_choice')
        if node['kind']=='condition':
            if node.get('variable') not in variables or node.get('operator') not in ('eq','ne','contains','gt','gte','lt','lte','is_set'):raise ValueError('Choose a collected input and condition operator')
            if not isinstance(node.get('value',''),str) or len(node.get('value',''))>1000:raise ValueError('Invalid condition value')
        if node['kind']=='wait' and (type(node.get('seconds')) is not int or not 1<=node['seconds']<=86400):raise ValueError('Delay must be between 1 second and 24 hours')
        if node['kind']=='action':
            if not isinstance(node.get('action'),str) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,99}',node['action']):raise ValueError('Choose a registered business action')
            if not isinstance(node.get('arguments',{}),dict):raise ValueError('Business action arguments must be an object')
            from relay_core.flows.action_contracts import resolve
            resolve(node.get('arguments',{}),{name:None for name in variables})
        if node['kind']=='topic':
            if not isinstance(node.get('title'),str) or not 1<=len(node['title'].strip())<=140:raise ValueError('Topic title must contain 1–140 characters')
            if node.get('status','Open') not in ('Open','Waiting','Resolved','Archived'):raise ValueError('Unsupported topic status')
            if not isinstance(node.get('category',''),str) or len(node.get('category',''))>140:raise ValueError('Topic category is too long')
        if node['kind']=='ticket' and node.get('category','Query') not in ('Query','Payment evidence','Support','Other'):
            raise ValueError('Unsupported ticket category')
    positions={node['id']:index for index,node in enumerate(value)}
    incoming={0:[set()]}
    for index,node in enumerate(value):
        if node['kind']=='condition':
            for target in (node.get('then'),node.get('otherwise')):
                if target not in positions or positions[target]<=index:raise ValueError('Condition branches must point to later steps')
        if 'next' in node and (node['kind'] in ('condition','end','handoff') or not isinstance(node['next'],str) or node['next'] not in positions or positions[node['next']]<=index):raise ValueError('Next step must point to a later step')
        paths=incoming.get(index,[])
        if not paths:raise ValueError('Every flow step must be reachable')
        guaranteed=set.intersection(*paths)
        references=set(re.findall(r'\{\{([a-z][a-z0-9_]{0,39})\}\}',node['text']+' '+str(node.get('title',''))))
        if node['kind']=='condition':references.add(node['variable'])
        if node['kind']=='action':
            from relay_core.flows.action_contracts import resolve
            resolve(node.get('arguments',{}),{name:None for name in guaranteed})
        if not references<=guaranteed:raise ValueError('An input may be skipped before this step uses it')
        if node['kind']=='input':guaranteed.add(node['variable'])
        targets=[] if node['kind'] in ('end','handoff') else [positions[node['then']],positions[node['otherwise']]] if node['kind']=='condition' else [positions[node['next']] if node.get('next') else index+1]
        for target in targets:
            if target<len(value):incoming.setdefault(target,[]).append(set(guaranteed))
    return value


def matches(node,values):
    actual=str(values.get(node['variable'],''));expected=node.get('value','');operator=node['operator']
    if operator=='is_set':return bool(actual.strip())
    if operator=='eq':return actual.casefold()==expected.casefold()
    if operator=='ne':return actual.casefold()!=expected.casefold()
    if operator=='contains':
        original=values.get(node['variable'])
        if isinstance(original,list):return any(str(item).casefold()==expected.casefold() for item in original)
        return expected.casefold() in actual.casefold()
    try:left=float(actual);right=float(expected)
    except (ValueError,TypeError):return False
    if not math.isfinite(left) or not math.isfinite(right):return False
    return {'gt':left>right,'gte':left>=right,'lt':left<right,'lte':left<=right}[operator]


def parse_input(node,value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=1000:raise ValueError('Enter 1–1000 characters')
    value=value.strip();kind=node['input_type']
    if node.get('optional') and value.casefold()=='skip':return ''
    if kind=='number':
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
        match=next((choice['value'] for choice in choice_options(node['choices']) if value.casefold() in (choice['label'].casefold(),choice['value'].casefold())),None)
        if match is None:raise ValueError('Choose: '+', '.join(choice['label'] for choice in choice_options(node['choices'])))
        value=match
    return value


def render(text,values):
    result=re.sub(r'\{\{([a-z][a-z0-9_]{0,39})\}\}',lambda match: ', '.join(str(item) for item in values[match[1]]) if isinstance(values.get(match[1]),list) else str(values.get(match[1],'')),text)
    if len(result)>4000:raise ValueError('Rendered step exceeds 4000 characters')
    return result


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
