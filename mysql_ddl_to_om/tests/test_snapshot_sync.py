from copy import deepcopy
import json
from unittest.mock import Mock, patch
import pytest
from mysql_ddl_to_om import ConversionError, convert_sql, fqn
from snapshot_sync import OMClient, apply_plan, make_plan

SCOPE={'service':'s','database':'default','schema':'shop','fqn':'s.default.shop'}
PARENT={'id':'parent','fullyQualifiedName':SCOPE['fqn']}


def snapshot(sql):
    tables,warnings=convert_sql(sql,service='s',database='default',schema='shop',allow_empty=True)
    return {'formatVersion':1,'scope':deepcopy(SCOPE),'tables':tables,'warnings':warnings,'sources':[]}


class FakeOM:
    def __init__(self,sql=''):
        self.entities={};self.events=[];self.n=0
        self.fail_create=None;self.fail_patch=None;self.ignore_patch=False
        for t in snapshot(sql)['tables']:self.create(t)
        self.events=[]
    def normalise(self,t):
        t['fullyQualifiedName']=SCOPE['fqn']+'.'+fqn(t['name'])
        t['databaseSchema']=deepcopy(PARENT)
        for c in t['columns']:
            c['fullyQualifiedName']=t['fullyQualifiedName']+'.'+fqn(c['name'])
            c['dataTypeDisplay']=c.get('dataTypeDisplay',c['dataType']).lower()
            c.setdefault('tags',[])
        for key in ('owners','domains'):
            for ref in t.get(key,[]):ref.update(name='server-name',href='https://om/ref')
        t.setdefault('tableConstraints',[]);t.setdefault('tags',[])
    def parent(self,scope):return deepcopy(PARENT)
    def list_tables(self,scope):return deepcopy(list(self.entities.values()))
    def get(self,identity):return deepcopy(self.entities[identity])
    def by_name(self,name):
        return next((deepcopy(t) for t in self.entities.values() if t['fullyQualifiedName']==name),None)
    def create(self,p):
        if p['name']==self.fail_create:raise ConversionError('simulated create failure')
        assert not self.by_name(SCOPE['fqn']+'.'+fqn(p['name']))
        assert not (any(c.get('constraint')=='PRIMARY_KEY' for c in p['columns']) and
                    any(c['constraintType']=='PRIMARY_KEY' for c in p.get('tableConstraints',[])))
        self.n+=1;t={**deepcopy(p),'id':str(self.n),'version':.1,'deleted':False}
        self.normalise(t);self.entities[t['id']]=t;self.events.append(('create',t['name']))
        return deepcopy(t)
    def patch(self,current,changes):
        if current['name']==self.fail_patch:raise ConversionError('simulated patch failure')
        t=self.entities[current['id']];assert t['version']==current['version']
        if not self.ignore_patch:t.update(deepcopy(changes))
        t['version']=round(t['version']+.1,1);self.normalise(t)
        self.events.append(('patch',t['name'],deepcopy(changes)));return deepcopy(t)
    def restore(self,identity):
        t=self.entities[identity];t['deleted']=False;t['version']=round(t['version']+.1,1)
        self.events.append(('restore',t['name']));return deepcopy(t)
    def delete(self,identity):
        t=self.entities[identity];t['deleted']=True;t['version']=round(t['version']+.1,1)
        self.events.append(('delete',t['name']))


def plan(om,sql,**kw):return make_plan(snapshot(sql),om.list_tables(SCOPE['fqn']),PARENT,exclusive=True,**kw)


def test_full_snapshot_add_modify_remove(tmp_path):
    om=FakeOM('CREATE TABLE orders(id INT PRIMARY KEY,state VARCHAR(8),obsolete INT); CREATE TABLE retired(id INT)')
    om.entities['1']['columns'][1].update(description='human note',tags=[{'tagFQN':'PII.Sensitive','source':'Classification','labelType':'Manual','state':'Confirmed'}])
    p=plan(om,'CREATE TABLE orders(id BIGINT PRIMARY KEY,state VARCHAR(32),delivered DATETIME); CREATE TABLE fresh(id INT)')
    assert p['targets'][1]['columnChanges']['removed']==['obsolete']
    assert p['softDeletes'][0]['name']=='retired' and not om.events
    result=apply_plan(om,p,journal_path=tmp_path/'journal.json')
    t=om.entities['1']
    assert [c['name'] for c in t['columns']]==['id','state','delivered']
    assert t['columns'][1]['description']=='human note'
    assert t['columns'][1]['tags'][0]['tagFQN']=='PII.Sensitive'
    assert om.entities['2']['deleted'] and om.events[-1]==('delete','retired')
    assert result['status']==json.loads((tmp_path/'journal.json').read_text())['status']=='succeeded'


def test_noop_idempotence():
    sql='CREATE TABLE t(id INT PRIMARY KEY)';om=FakeOM(sql);p=plan(om,sql)
    apply_plan(om,p);apply_plan(om,p);assert not om.events


def test_table_and_column_rename_metadata():
    om=FakeOM('CREATE TABLE orders(id INT PRIMARY KEY,status VARCHAR(8))')
    om.entities['1'].update(description='table note',owners=[{'id':'o','type':'team'}],domains=[{'id':'d','type':'domain'}],extension={'purpose':'orders'})
    om.entities['1']['columns'][1].update(description='column note',tags=[{'tagFQN':'PII.Sensitive','source':'Classification','labelType':'Manual','state':'Confirmed'}])
    sql='CREATE TABLE customer_orders(id INT PRIMARY KEY,order_status VARCHAR(16))'
    hints={'tableRenames':[{'from':'orders','to':'customer_orders'}],'columnRenames':[{'table':'customer_orders','from':'status','to':'order_status'}]}
    p=plan(om,sql,renames=hints)
    with pytest.raises(ConversionError,match='ID'):apply_plan(om,p)
    assert not om.events
    apply_plan(om,p,acknowledge_rename=True)
    t=om.by_name('s.default.shop.customer_orders')
    assert t['id']!='1' and om.entities['1']['deleted']
    assert t['description']=='table note' and t['owners'][0]['id']=='o' and t['extension']=={'purpose':'orders'}
    assert t['columns'][1]['name']=='order_status' and t['columns'][1]['description']=='column note'
    assert t['columns'][1]['tags'][0]['tagFQN']=='PII.Sensitive'
    om.events=[];apply_plan(om,plan(om,sql,renames=hints),acknowledge_rename=True);assert not om.events


def test_column_rename_same_table_id():
    om=FakeOM('CREATE TABLE t(id INT PRIMARY KEY,old_col INT)');om.entities['1']['columns'][1]['description']='note'
    p=plan(om,'CREATE TABLE t(id INT PRIMARY KEY,new_col INT)',renames={'columnRenames':[{'table':'t','from':'old_col','to':'new_col'}]})
    apply_plan(om,p);assert om.entities['1']['columns'][1]['name']=='new_col'
    assert om.entities['1']['columns'][1]['description']=='note' and not om.entities['1']['deleted']


def test_restore_same_id():
    om=FakeOM('CREATE TABLE t(id INT)');om.delete('1');om.events=[]
    p=plan(om,'CREATE TABLE t(id BIGINT,added INT)');assert p['targets'][0]['action']=='restore'
    apply_plan(om,p);assert not om.entities['1']['deleted'] and len(om.entities['1']['columns'])==2
    assert om.events[0]==('restore','t')


def test_empty_and_thresholds():
    om=FakeOM('CREATE TABLE t(id INT)')
    with pytest.raises(ConversionError,match='Empty'):plan(om,'')
    with pytest.raises(ConversionError,match='ratio'):plan(om,'',allow_empty=True)
    p=plan(om,'',allow_empty=True,max_delete_ratio=1);apply_plan(om,p);assert om.entities['1']['deleted']


def test_max_deletes():
    om=FakeOM('CREATE TABLE a(id INT); CREATE TABLE b(id INT)')
    with pytest.raises(ConversionError,match='count'):plan(om,'',allow_empty=True,max_deletes=1,max_delete_ratio=1)


def test_exclusive_required():
    with pytest.raises(ConversionError,match='ALL'):make_plan(snapshot('CREATE TABLE t(id INT)'),[],PARENT)


@pytest.mark.parametrize('mutation',['version','concurrent_create','plan_tamper'])
def test_stale_or_tampered_no_writes(mutation):
    om=FakeOM('CREATE TABLE t(id INT)');p=plan(om,'CREATE TABLE t(id BIGINT)')
    if mutation=='version':om.entities['1']['version']=.2
    elif mutation=='concurrent_create':om.create(snapshot('CREATE TABLE other(id INT)')['tables'][0]);om.events=[]
    else:p['softDeletes'].append({'id':'1','name':'t'})
    with pytest.raises(ConversionError):apply_plan(om,p)
    assert not om.events


def test_create_failure_no_deletes(tmp_path):
    om=FakeOM('CREATE TABLE old(id INT); CREATE TABLE remain(id INT)')
    p=plan(om,'CREATE TABLE new(id INT); CREATE TABLE remain(id INT)');om.fail_create='new'
    with pytest.raises(ConversionError):apply_plan(om,p,journal_path=tmp_path/'j.json')
    assert not om.entities['1']['deleted']
    assert json.loads((tmp_path/'j.json').read_text())['status']=='failed_replan_required'


def test_ignored_patch_blocks_delete():
    om=FakeOM('CREATE TABLE t(id INT); CREATE TABLE old(id INT)');p=plan(om,'CREATE TABLE t(id BIGINT)');om.ignore_patch=True
    with pytest.raises(ConversionError,match='persist'):apply_plan(om,p)
    assert not om.entities['2']['deleted']


def test_fk_cycles_deferred():
    om=FakeOM();sql='CREATE TABLE a(id INT PRIMARY KEY,bid INT,FOREIGN KEY(bid) REFERENCES b(id)); CREATE TABLE b(id INT PRIMARY KEY,aid INT,FOREIGN KEY(aid) REFERENCES a(id))'
    apply_plan(om,plan(om,sql));assert om.events[0][:2]==('create','a') and om.events[1][:2]==('create','b')
    assert om.entities['1']['tableConstraints'][-1]['constraintType']=='FOREIGN_KEY'
    assert om.entities['2']['tableConstraints'][-1]['constraintType']=='FOREIGN_KEY'


def test_missing_fk_target_rejected():
    with pytest.raises(ConversionError,match='Foreign key'):plan(FakeOM(),'CREATE TABLE t(id INT,FOREIGN KEY(id) REFERENCES missing(id))')


@pytest.mark.parametrize('hints',[
 {'tableRenames':[{'from':'a','to':'b'},{'from':'b','to':'a'}]},
 {'tableRenames':[{'from':'a','to':'b'},{'from':'a','to':'c'}]},
 {'tableRenames':[{'from':'missing','to':'b'}]},
 {'columnRenames':[{'table':'b','from':'missing','to':'id'}]},
])
def test_invalid_rename_hints(hints):
    with pytest.raises(ConversionError):plan(FakeOM('CREATE TABLE a(id INT)'),'CREATE TABLE b(id INT)',renames=hints)


def test_resume_partial_rename():
    om=FakeOM('CREATE TABLE a(old_col INT)');om.entities['1']['columns'][0]['description']='note'
    sql='CREATE TABLE b(new_col INT)';hints={'tableRenames':[{'from':'a','to':'b'}],'columnRenames':[{'table':'b','from':'old_col','to':'new_col'}]}
    p=plan(om,sql,renames=hints);om.fail_patch='b';original=om.create
    def omit_note(payload):
        value=deepcopy(payload);value['columns'][0].pop('description',None);return original(value)
    om.create=omit_note
    with pytest.raises(ConversionError):apply_plan(om,p,acknowledge_rename=True)
    assert not om.entities['1']['deleted']
    with pytest.raises(ConversionError,match='Both'):plan(om,sql,renames=hints)
    om.fail_patch=None;apply_plan(om,plan(om,sql,renames=hints,resume=True),acknowledge_rename=True)
    assert om.entities['1']['deleted'] and om.by_name('s.default.shop.b')['columns'][0]['description']=='note'


def response(payload):
    r=Mock();r.status_code=200;r.content=b'{}';r.json.return_value=payload;return r


def test_pagination():
    rows=FakeOM('CREATE TABLE a(id INT); CREATE TABLE b(id INT)').list_tables(SCOPE['fqn'])
    with patch('requests.Session') as factory:
        s=factory.return_value;s.request.side_effect=[response({'data':[rows[0]],'paging':{'after':'cursor'}}),response({'data':[rows[1]],'paging':{}})]
        c=OMClient('https://om.example','token');assert len(c.list_tables(SCOPE['fqn']))==2
        calls=s.request.call_args_list;assert calls[1].kwargs['params']['after']=='cursor'
        assert calls[0].kwargs['params']['include']=='all' and calls[0].kwargs['params']['databaseSchema']==SCOPE['fqn']


def test_scope_and_pagination_loop_guard():
    with patch('requests.Session') as factory:
        s=factory.return_value;t=FakeOM('CREATE TABLE t(id INT)').entities['1'];t['databaseSchema']['fullyQualifiedName']='other'
        s.request.return_value=response({'data':[t],'paging':{}});c=OMClient('https://om.example','token')
        with pytest.raises(ConversionError,match='scope'):c.list_tables(SCOPE['fqn'])
        s.request.return_value=response({'data':[],'paging':{'after':'same'}})
        with pytest.raises(ConversionError,match='cursor'):c.list_tables(SCOPE['fqn'])


def test_patch_tests_and_delete_api_parameters():
    with patch('requests.Session') as factory:
        s=factory.return_value;s.request.return_value=response({});c=OMClient('https://om.example/api','token')
        c.patch({'id':'i','name':'t','version':1.2},{'columns':[]});call=s.request.call_args
        assert call.args[:2]==('PATCH','https://om.example/api/v1/tables/i')
        assert call.kwargs['json'][0]=={'op':'test','path':'/version','value':1.2}
        assert call.kwargs['headers']['Content-Type']=='application/json-patch+json'
        c.delete('i');assert s.request.call_args.kwargs['params']=={'hardDelete':'false','recursive':'true'}


def test_drop_replan_noop():
    om=FakeOM('CREATE TABLE a(id INT); CREATE TABLE b(id INT)');sql='CREATE TABLE a(id INT)'
    apply_plan(om,plan(om,sql));om.events=[];apply_plan(om,plan(om,sql));assert not om.events


def test_external_fk_missing_blocks_all_writes():
    om=FakeOM()
    p=plan(om,'CREATE TABLE t(id INT, FOREIGN KEY(id) REFERENCES external.parent(id))')
    with pytest.raises(ConversionError,match='External'):
        apply_plan(om,p)
    assert not om.events


def test_delete_source_changed_during_apply_preserved():
    om=FakeOM('CREATE TABLE old(id INT); CREATE TABLE remain(id INT)')
    p=plan(om,'CREATE TABLE remain(id BIGINT)')
    original=om.patch
    def concurrent(current,changes):
        value=original(current,changes)
        om.entities['1']['description']='concurrent annotation'
        return value
    om.patch=concurrent
    with pytest.raises(ConversionError,match='Delete source changed'):
        apply_plan(om,p)
    assert not om.entities['1']['deleted']


def test_constraint_order_normalization():
    from snapshot_sync import constraints_equal
    a=[{'constraintType':'PRIMARY_KEY','columns':['b','a']}]
    b=[{'constraintType':'PRIMARY_KEY','columns':['a','b']}]
    assert constraints_equal(a,b)


def test_empty_converter_opt_in(tmp_path):
    from mysql_ddl_to_om import convert_files
    path=tmp_path/'schemas.sql';path.write_text('-- empty database\n')
    with pytest.raises(ConversionError):
        convert_files([path],service='s',database='default',schema='shop')
    bundle=convert_files([path],service='s',database='default',schema='shop',allow_empty=True)
    assert bundle['tables']==[] and bundle['scope']==SCOPE


def test_cli_plan_and_apply(tmp_path):
    from snapshot_sync import main
    om=FakeOM('CREATE TABLE t(id INT)')
    om.close=lambda:None
    bundle_path=tmp_path/'models.json';bundle_path.write_text(json.dumps(snapshot('CREATE TABLE t(id BIGINT)')))
    output=tmp_path/'plan.json';journal=tmp_path/'journal.json'
    with patch('snapshot_sync.OMClient',return_value=om):
        assert main(['plan',str(bundle_path),'--url','https://om.example','--exclusive-schema','--output',str(output)])==0
        assert not om.events
        assert main(['apply',str(output),'--url','https://om.example','--journal',str(journal)])==0
    assert om.entities['1']['columns'][0]['dataType']=='BIGINT'
    assert json.loads(journal.read_text())['status']=='succeeded'
