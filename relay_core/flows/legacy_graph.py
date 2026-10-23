"""Convert supported legacy DAGs into reviewable Relay steps; never activates them."""
from copy import deepcopy
from relay_core.flows.contracts import definition


def answer_ref(value):
    if isinstance(value,dict):
        if set(value)=={'var'}:
            ref=value['var']
            if not isinstance(ref,str) or not ref.startswith('answers.'):
                raise ValueError('Only collected answer references can be migrated')
            return {'var':ref.removeprefix('answers.')}
        return {k:answer_ref(v) for k,v in value.items()}
    if isinstance(value,list):return [answer_ref(v) for v in value]
    return value


def convert(graph):
    if not isinstance(graph,dict) or graph.get('schema_version')!=1:
        raise ValueError('Choose a version 1 legacy graph')
    raw=graph.get('nodes',[]);edges=graph.get('edges',[])
    if not isinstance(raw,list) or not 1<=len(raw)<=100 or not isinstance(edges,list) or len(edges)>300:
        raise ValueError('Legacy graph exceeds conversion limits')
    nodes={};out={}
    for node in raw:
        if not isinstance(node,dict) or not isinstance(node.get('id'),str) or node['id'] in nodes:
            raise ValueError('Legacy graph has invalid or duplicate node IDs')
        nodes[node['id']]=node;out[node['id']]=[]
    for edge in edges:
        if not isinstance(edge,dict) or edge.get('source') not in nodes or edge.get('target') not in nodes:
            raise ValueError('Legacy edge points to an unknown node')
        out[edge['source']].append(edge)
    starts=[n['id'] for n in raw if n.get('type')=='start']
    if len(starts)!=1 or len(out[starts[0]])!=1:
        raise ValueError('Legacy graph needs one start with one successor')
    converted={};links={}
    for key,node in nodes.items():
        config=node.get('config') or {};kind=node.get('type');routes=out[key]
        supported={'start':{'label'},'ask_input':{'label','message','answer_key','input_type','options','minimum','maximum','integer_only','optional','required'},'condition':{'label'},'action':{'label','action','input','output_key'},'end':{'label','message'}}
        if kind not in supported or not isinstance(config,dict) or set(config)-supported[kind]:raise ValueError('Unsupported legacy configuration on '+key)
        if kind=='start':continue
        row={'id':key}
        if kind=='ask_input':
            row.update(kind='input',text=config.get('message',''),variable=config.get('answer_key'),input_type={'radio':'choice','multi_select':'multi_choice'}.get(config.get('input_type'),config.get('input_type')))
            if 'required' in config:
                if type(config['required']) is not bool:raise ValueError('Legacy required flag must be boolean')
                row['optional']=not config['required']
            for field in ('minimum','maximum','integer_only','optional'):
                if field in config:row[field]=config[field]
            if row['input_type'] in ('choice','multi_choice'):row['choices']=deepcopy(config.get('options'))
        elif kind=='end':row.update(kind='end',text=config.get('message',''))
        elif kind=='action':
            values=answer_ref(config.get('input',{}));action=config.get('action')
            if not isinstance(values,dict):raise ValueError('Legacy action input must be an object')
            if action=='topic.upsert':
                if set(values)-{'topic_key','title','summary','category','status','confidence'}:raise ValueError('Unsupported legacy topic action fields')
                if values.get('confidence',100)!=100:raise ValueError('Non-default topic confidence needs manual conversion')
                row.update(kind='topic',title=values.get('title',''),text=values.get('summary') or values.get('title',''),category=values.get('category',''),status=values.get('status','Open'))
            else:row.update(kind='action',text='',action=action,arguments=values)
        elif kind=='condition':
            defaults=[e for e in routes if e.get('default')];tests=[e for e in routes if not e.get('default')]
            if len(defaults)!=1 or not tests:raise ValueError('Legacy conditions need tests and exactly one default route')
            for index,edge in enumerate(tests):
                test=edge.get('when',{});ref=answer_ref(test.get('left'))
                if test.get('op')!='eq' or not isinstance(ref,dict) or set(ref)!={'var'} or not isinstance(test.get('right'),str):
                    raise ValueError('Only equality conditions on collected answers are currently supported')
                ident=key if index==0 else key+'_test_'+str(index)
                if ident!=key and ident in nodes:raise ValueError('Generated condition ID conflicts with source node')
                otherwise=key+'_test_'+str(index+1) if index+1<len(tests) else defaults[0]['target']
                converted[ident]={'id':ident,'kind':'condition','text':'','variable':ref['var'],'operator':'eq','value':test['right'],'then':edge['target'],'otherwise':otherwise}
                links[ident]=[edge['target'],otherwise]
            continue
        else:raise ValueError('Unsupported legacy node: '+str(kind))
        if kind=='end':
            if routes:raise ValueError('Terminal legacy node has outgoing edges')
            links[key]=[]
        else:
            if len(routes)!=1 or routes[0].get('when') or routes[0].get('default'):raise ValueError('Non-branch step needs one unconditional successor')
            row['next']=routes[0]['target'];links[key]=[row['next']]
        converted[key]=row
    # Stable topological order preserves forward-only execution and branch joins.
    degrees={key:0 for key in converted}
    for targets in links.values():
        for target in targets:
            if target not in degrees:raise ValueError('Legacy graph loops into its start')
            degrees[target]+=1
    ready=[key for key,count in degrees.items() if count==0];ordered=[]
    while ready:
        key=ready.pop(0);ordered.append(converted[key])
        for target in links[key]:
            degrees[target]-=1
            if degrees[target]==0:ready.append(target)
    if len(ordered)!=len(converted):raise ValueError('Cyclic legacy graphs need manual conversion')
    if not ordered or ordered[0]['id']!=out[starts[0]][0]['target']:raise ValueError('Legacy graph has disconnected steps')
    return {'nodes':definition(ordered),'triggers':deepcopy(graph.get('triggers',[])),
            'requires_review':True,'enabled':False}
