from pathlib import Path
import json,subprocess
from unittest.mock import patch
import pytest
from mysql_ddl_to_om import ConversionError
from pr_diff_to_om import generate,write_output,main
CONFIG={'databases':[{'path':'mysql/shop/schemas.sql','service':'mysql_prod','database':'default','schema':'shop'}]}
SCOPE='mysql_prod.default.shop'

def git(repo,*args):
 return subprocess.run(['git','-C',str(repo),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode().strip()
@pytest.fixture
def repo(tmp_path):
 git(tmp_path,'init','-q');git(tmp_path,'config','user.email','tests@example.invalid');git(tmp_path,'config','user.name','Tests');git(tmp_path,'config','commit.gpgsign','false');return tmp_path

def commit(repo,text,path='mysql/shop/schemas.sql'):
 p=repo/path
 if text is None:p.unlink()
 else:p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 git(repo,'add','-A');git(repo,'commit','-qm','snapshot');return git(repo,'rev-parse','HEAD')

def test_diff_create_update_drop_no_network(repo):
 a=commit(repo,'CREATE TABLE users(id INT,name VARCHAR(8)); CREATE TABLE obsolete(id INT); CREATE TABLE unchanged(id INT)')
 b=commit(repo,'CREATE TABLE users(id BIGINT,name VARCHAR(32),age INT); CREATE TABLE fresh(id INT); CREATE TABLE unchanged(id INT)')
 with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):r=generate(repo,a,b,CONFIG)
 assert r['counts']=={'create':1,'update':1,'drop':1,'rename':0,'upsert':0}
 assert {c['name'] for c in r['changes']}=={'users','fresh','obsolete'}
 c=next(c for c in r['changes'] if c['name']=='users');assert c['columns']['added']==['age'] and c['columns']['modified']==['id','name']
 assert all(x['method'] in {'PUT','PATCH','DELETE'} for x in r['requests'])
 assert r['requests'][-1]['method']=='DELETE' and r['requests'][-1]['query']['hardDelete']=='false'
 assert r['requests'][-1]['path'].endswith('/name/'+SCOPE+'.obsolete')

def test_full_all_and_diff_noop(repo):
 h=commit(repo,'CREATE TABLE a(id INT); CREATE TABLE b(id INT)');r=generate(repo,None,h,CONFIG,mode='full')
 assert r['mode']=='full' and r['baseCommit'] is None and r['counts']['upsert']==2
 assert all(c['change']=='upsert' for c in r['changes']) and all(x['method']!='DELETE' for x in r['requests'])
 assert generate(repo,h,h,CONFIG)['changes']==[]

def test_formatting_order_quoting_no_changes(repo):
 a=commit(repo,"CREATE TABLE a(id INT); CREATE TABLE shop.b(v VARCHAR(12) COMMENT 'Hello')")
 b=commit(repo,"-- note\nCREATE TABLE IF NOT EXISTS `b` (`v` VARCHAR(12) COMMENT 'Hello'); CREATE TABLE `shop`.`a` (`id` INT);")
 assert generate(repo,a,b,CONFIG)['changes']==[]

def test_comments_indexes_and_field_drop(repo):
 a=commit(repo,"CREATE TABLE t(id INT COMMENT 'old',gone INT) COMMENT='table'")
 b=commit(repo,'CREATE TABLE t(id INT,KEY idx(id))');r=generate(repo,a,b,CONFIG)
 assert r['counts']['update']==1 and r['changes'][0]['columns']['removed']==['gone']
 p={p['path']:p['value'] for p in r['requests'][1]['body']};assert p['/description'] is None and p['/columns'][0]['description'] is None

def test_file_deleted(repo):
 a=commit(repo,'CREATE TABLE a(id INT); CREATE TABLE b(id INT)');b=commit(repo,None);r=generate(repo,a,b,CONFIG)
 assert r['counts']['drop']==2 and all(x['method']=='DELETE' for x in r['requests'])

def test_file_added(repo):
 a=commit(repo,'initial','README.md');b=commit(repo,'CREATE TABLE t(id INT)');assert generate(repo,a,b,CONFIG)['counts']['create']==1

def test_empty_full(repo):
 h=commit(repo,'-- no tables\n');r=generate(repo,None,h,CONFIG,mode='full');assert r['changes']==r['requests']==[]

def test_rename_explicit_and_default(repo):
 a=commit(repo,'CREATE TABLE old(id INT)');b=commit(repo,'CREATE TABLE new(id INT)');r=generate(repo,a,b,CONFIG)
 assert r['counts']['create']==r['counts']['drop']==1
 hints={'tableRenames':[{'schemaFqn':SCOPE,'from':'old','to':'new'}]};r=generate(repo,a,b,CONFIG,renames=hints)
 assert r['counts']['rename']==1 and [x['method'] for x in r['requests']]==['PUT','PATCH','DELETE']
 assert r['requests'][-1]['tableFqn']==SCOPE+'.old'

def test_path_rename_same_scope(repo):
 a=commit(repo,'CREATE TABLE t(id INT)');p=repo/'new/shop/schemas.sql';p.parent.mkdir(parents=True);(repo/'mysql/shop/schemas.sql').rename(p)
 git(repo,'add','-A');git(repo,'commit','-qm','move');b=git(repo,'rev-parse','HEAD')
 cfg={'databases':CONFIG['databases']+[{**CONFIG['databases'][0],'path':'new/shop/schemas.sql'}]}
 assert generate(repo,a,b,cfg)['changes']==[]

def test_multiple_databases(repo):
 a=commit(repo,'CREATE TABLE a(id INT)');path='mysql/payment/schemas.sql';b=commit(repo,'CREATE TABLE invoice(id BIGINT)',path)
 cfg={'databases':CONFIG['databases']+[{'path':path,'service':'mysql_prod','database':'default','schema':'payment'}]};r=generate(repo,a,b,cfg)
 assert r['counts']['create']==1 and r['changes'][0]['scope'].endswith('.payment')
 assert generate(repo,None,b,cfg,mode='full')['counts']['upsert']==2

def test_unmapped_schema_fails(repo):
 a=commit(repo,'CREATE TABLE t(id INT)');b=commit(repo,'CREATE TABLE t(id INT)','other/schemas.sql')
 with pytest.raises(ConversionError,match='missing configuration'):generate(repo,a,b,CONFIG)
 with pytest.raises(ConversionError,match='missing configuration'):generate(repo,None,b,CONFIG,mode='full')

def test_full_missing_file_fails(repo):
 h=commit(repo,'text','README.md')
 with pytest.raises(ConversionError,match='every configured scope'):generate(repo,None,h,CONFIG,mode='full')

@pytest.mark.parametrize('sql',['ALTER TABLE t ADD x INT','CREATE TABLE t(x POINT)','CREATE TABLE t(x INT); DROP TABLE t'])
def test_invalid_input(repo,sql):
 a=commit(repo,'CREATE TABLE t(id INT)');b=commit(repo,sql)
 with pytest.raises(ConversionError):generate(repo,a,b,CONFIG)

def test_worktree_ignored(repo):
 a=commit(repo,'CREATE TABLE t(id INT)');b=commit(repo,'CREATE TABLE t(id BIGINT)');(repo/'mysql/shop/schemas.sql').write_text('INVALID')
 assert generate(repo,a,b,CONFIG)['changes'][0]['payload']['columns'][0]['dataType']=='BIGINT'

def test_symlink_rejected(repo):
 a=commit(repo,'CREATE TABLE t(id INT)');p=repo/'mysql/shop/schemas.sql';p.unlink();p.symlink_to('/etc/passwd');git(repo,'add','-A');git(repo,'commit','-qm','symlink')
 with pytest.raises(ConversionError,match='Symlinks'):generate(repo,a,git(repo,'rev-parse','HEAD'),CONFIG)

def test_mergebase_vs_direct(repo):
 root=commit(repo,'CREATE TABLE a(id INT)');git(repo,'branch','target');h=commit(repo,'CREATE TABLE a(id INT); CREATE TABLE feature_table(id INT)');git(repo,'checkout','-q','target');b=commit(repo,'CREATE TABLE a(id INT); CREATE TABLE target_table(id INT)')
 r=generate(repo,b,h,CONFIG);assert r['comparisonBaseCommit']==root and r['counts']['create']==1 and r['counts']['drop']==0
 assert generate(repo,b,h,CONFIG,comparison='direct')['counts']['drop']==1

def test_fk_cycle_requests_order(repo):
 h=commit(repo,'CREATE TABLE a(id INT PRIMARY KEY,bid INT,FOREIGN KEY(bid) REFERENCES b(id)); CREATE TABLE b(id INT PRIMARY KEY,aid INT,FOREIGN KEY(aid) REFERENCES a(id))')
 r=generate(repo,None,h,CONFIG,mode='full');assert [x['method'] for x in r['requests']]==['PUT','PUT','PATCH','PATCH']
 assert all(c['constraintType']!='FOREIGN_KEY' for x in r['requests'][:2] for c in x['body']['tableConstraints'])

def test_dangling_fk(repo):
 a=commit(repo,'CREATE TABLE p(id INT PRIMARY KEY); CREATE TABLE c(id INT,FOREIGN KEY(id) REFERENCES p(id))');b=commit(repo,'CREATE TABLE c(id INT,FOREIGN KEY(id) REFERENCES p(id))')
 with pytest.raises(ConversionError,match='dangling'):generate(repo,a,b,CONFIG)

def test_output_cli(repo,tmp_path):
 h=commit(repo,'CREATE TABLE t(id INT PRIMARY KEY)');config=tmp_path/'config.json';config.write_text(json.dumps(CONFIG));out=tmp_path/'out'
 assert main(['--mode','full','--repo',str(repo),'--head',h,'--config',str(config),'--output',str(out)])==0
 r=json.loads((out/'om-requests.json').read_text());assert r['counts']['upsert']==1
 assert json.loads((out/'000-put.json').read_text())['name']=='t' and len(json.loads((out/'upserts.json').read_text()))==1
 with pytest.raises(ConversionError,match='exists'):write_output(out,r)

def test_mode_requirements(repo):
 h=commit(repo,'CREATE TABLE t(id INT)')
 with pytest.raises(ConversionError,match='--base'):generate(repo,None,h,CONFIG)
 with pytest.raises(ConversionError,match='only meaningful'):generate(repo,None,h,CONFIG,mode='full',renames={'tableRenames':[]})


def test_annotations_diff_and_full(repo):
 a=commit(repo,"CREATE TABLE t(email VARCHAR(128) COMMENT 'User email address\n@om.security=L2\n@om.tag=PII.Email')")
 b=commit(repo,"CREATE TABLE t(email VARCHAR(128) COMMENT 'User email address\n@om.security=L3\n@om.tag=PII.Email')")
 for kwargs in ({'base_ref':a,'mode':'diff'},{'base_ref':None,'mode':'full'}):
  r=generate(repo,kwargs['base_ref'],b,CONFIG,mode=kwargs['mode'])
  c=r['changes'][0]['payload']['columns'][0]
  assert c['description']=='User email address'
  assert {t['tagFQN'] for t in c['tags']}=={'Security.L3','PII.Email'}
  assert '@om.security=L3' in r['changes'][0]['payload']['schemaDefinition']
  patch=r['requests'][-1]
  assert patch['method']=='PATCH'
  fields={p['path']:p['value'] for p in patch['body']}
  assert {t['tagFQN'] for t in fields['/columns'][0]['tags']}=={'Security.L3','PII.Email'}


def test_annotation_removed_generates_explicit_empty_tag_list(repo):
 a=commit(repo,"CREATE TABLE t(id INT COMMENT 'ID\n@om.security=L3')")
 b=commit(repo,"CREATE TABLE t(id INT COMMENT 'ID')")
 r=generate(repo,a,b,CONFIG)
 fields={p['path']:p['value'] for p in r['requests'][-1]['body']}
 assert fields['/columns'][0]['tags']==[]


def test_table_annotation_and_custom_classification(repo):
 h=commit(repo,"CREATE TABLE t(id INT) COMMENT='Business table\n@om.security=Confidential'")
 r=generate(repo,None,h,CONFIG,mode='full',security_classification='DataSecurity')
 p=r['changes'][0]['payload'];assert p['description']=='Business table'
 assert p['tags'][0]['tagFQN']=='DataSecurity.Confidential'
 assert p['tags'][0]['source']=='Classification' and p['tags'][0]['state']=='Confirmed'


@pytest.mark.parametrize('annotation',['@om.unknown=L3','inline @om.security=L3','@om.tag=MissingClassification','@om.security=L2\n@om.security=L3','@om.security=Security.L3'])
def test_invalid_annotation_fails(repo,annotation):
 h=commit(repo,"CREATE TABLE t(id INT COMMENT 'ID\n"+annotation+"')")
 with pytest.raises(ConversionError):generate(repo,None,h,CONFIG,mode='full')


def test_duplicate_tags_deduplicated(repo):
 h=commit(repo,"CREATE TABLE t(id INT COMMENT '@om.security=L3\n@om.tag=Security.L3')")
 r=generate(repo,None,h,CONFIG,mode='full')
 assert len(r['changes'][0]['payload']['columns'][0]['tags'])==1


def test_identifier_with_dot_and_space(repo):
 a=commit(repo,'CREATE TABLE `order.detail` (`customer name` VARCHAR(8), `a.b` INT)')
 b=commit(repo,'CREATE TABLE `order.detail` (`customer name` VARCHAR(16), `a.b` INT)')
 r=generate(repo,a,b,CONFIG)
 p=r['changes'][0]['payload'];assert p['name']=='order.detail'
 assert p['columns'][0]['name']=='customer name' and p['columns'][1]['name']=='a.b'
 assert r['requests'][0]['tableFqn']==SCOPE+'."order.detail"'


def test_ci_shell_entrypoint_full_mode(repo,tmp_path):
 import os
 head=commit(repo,'CREATE TABLE t(id INT)')
 config=tmp_path/'mapping.json';config.write_text(json.dumps(CONFIG))
 out=tmp_path/'ci-out'
 script=Path(__file__).parents[1]/'schema-ci.sh'
 env={**os.environ,'SCHEMA_MODE':'full','SCHEMA_REPO':str(repo),'SCHEMA_HEAD_SHA':head,
      'SCHEMA_MAPPING':str(config),'SCHEMA_OUTPUT_DIR':str(out)}
 result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 assert json.loads((out/'om-requests.json').read_text())['counts']['upsert']==1
