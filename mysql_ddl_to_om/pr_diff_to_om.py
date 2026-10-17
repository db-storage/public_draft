#!/usr/bin/env python3
"""Generate OM API requests from Git base/head schema snapshots. No OM reads/writes."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from urllib.parse import quote

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

from mysql_ddl_to_om import ConversionError, convert_sql, fqn


def require(condition, message):
    if not condition:
        raise ConversionError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                                     separators=(',',':')).encode()).hexdigest()


class GitRepository:
    def __init__(self,path):
        self.path=Path(path).resolve()
        self.run('rev-parse','--show-toplevel')

    def run(self,*args):
        result=subprocess.run(['git','--literal-pathspecs','-C',str(self.path),*args],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        if result.returncode:
            raise ConversionError('Git operation failed: '+args[0]+'. Ensure both commits/history exist locally.')
        return result.stdout

    def commit(self,ref):
        return self.run('rev-parse','--verify','--end-of-options',ref+'^{commit}').decode().strip()

    def changed(self,base,head):
        raw=self.run('diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',base,head,'--')
        return {p.decode('utf-8') for p in raw.split(b'\0') if p}

    def paths(self,commit):
        raw=self.run('ls-tree','-r','-z','--name-only',commit)
        return {p.decode('utf-8') for p in raw.split(b'\0') if p}

    def blob(self,commit,path):
        raw=self.run('ls-tree','-z',commit,'--',path)
        if not raw:
            return None,None
        entries=[x for x in raw.split(b'\0') if x]
        require(len(entries)==1,'Schema path must resolve to exactly one ordinary file: '+path)
        meta,actual=entries[0].split(b'\t',1)
        mode,kind,identity=meta.decode().split()
        require(actual.decode()==path and kind=='blob' and mode in {'100644','100755'},
                'Symlinks/directories/submodules are not schema files: '+path)
        return self.run('cat-file','blob',identity),identity


def load_config(config):
    require(set(config)=={'databases'} and isinstance(config['databases'],list) and config['databases'],
            'Invalid config: nonempty databases array required')
    paths,groups={},{}
    for row in config['databases']:
        require(set(row)=={'path','service','database','schema'},'Each mapping needs path/service/database/schema')
        require(all(isinstance(v,str) and v for v in row.values()),'Mapping values must be nonempty strings')
        path=row['path'];parts=PurePosixPath(path)
        require(not parts.is_absolute() and '..' not in parts.parts and str(parts)==path and '\\' not in path,
                'Use a normalized repository-relative POSIX path')
        require(path not in paths,'Duplicate mapping path: '+path)
        scope={k:row[k] for k in ('service','database','schema')}
        scope['fqn']=fqn(scope['service'],scope['database'],scope['schema'])
        paths[path]=scope['fqn']
        group=groups.setdefault(scope['fqn'],{'scope':scope,'paths':[]})
        require(group['scope']==scope,'Conflicting schema mappings')
        group['paths'].append(path)
    return paths,groups


def parse_snapshot(raw,scope,origin,security_classification='Security'):
    if raw is None:
        return {},[]
    text=raw.decode('utf-8-sig')
    # Validate the ORIGINAL SQL first (including executable comments and unknown clauses).
    _,warnings=convert_sql(text,service=scope['service'],database=scope['database'],
                           schema=scope['schema'],origin=origin,allow_empty=True,
                           security_classification=security_classification)
    tables={}
    for statement in sqlglot.parse(text,read='mysql',error_level=ErrorLevel.RAISE):
        if statement is None or isinstance(statement,exp.Semicolon):
            continue
        normalized=statement.copy()
        normalized.set('exists',False)
        normalized.this.this.set('db',None)  # scope has already been checked by converter
        # Quote every identifier to canonicalize style without breaking names
        # containing spaces, dots, reserved words or non-ASCII characters.
        canonical=normalized.sql(dialect='mysql',comments=False,identify=True)
        payload=convert_sql(canonical,service=scope['service'],database=scope['database'],
                            schema=scope['schema'],origin=origin,
                            security_classification=security_classification)[0][0]
        name=payload['name']
        require(name not in tables,'Duplicate CREATE TABLE: '+origin+':'+name)
        tables[name]={'payload':payload,'canonicalDDL':canonical,'source':origin}
    return tables,warnings


def collect(repo,commit,group,security_classification='Security'):
    tables,warnings,files={},[],[]
    for path in group['paths']:
        raw,oid=repo.blob(commit,path)
        parsed,report=parse_snapshot(raw,group['scope'],path,security_classification)
        require(not (tables.keys() & parsed.keys()),'Table defined twice in the same scope: '+group['scope']['fqn'])
        tables.update(parsed);warnings.extend(report)
        files.append({'path':path,'blobId':oid,'present':raw is not None})
    return tables,warnings,files


def column_changes(before,after):
    old={c['name']:c for c in before.get('columns',[])}
    new={c['name']:c for c in after.get('columns',[])}
    return {'added':sorted(new.keys()-old.keys()),'removed':sorted(old.keys()-new.keys()),
            'modified':sorted(n for n in old.keys() & new.keys() if old[n]!=new[n])}


def compare(before,after,scope,renames):
    remaining_old=set(before);remaining_new=set(after);changes=[]
    mapping={};targets=set()
    for row in renames:
        require(set(row)=={'schemaFqn','from','to'},'Invalid tableRenames entry')
        if row['schemaFqn']!=scope:
            continue
        a,b=row['from'],row['to']
        require(a!=b and a not in mapping and b not in targets,'Conflicting table rename')
        mapping[a]=b;targets.add(b)
    require(not (mapping.keys() & targets),'Rename chains/swaps are unsupported')
    for a,b in sorted(mapping.items()):
        require(a in before and a not in after and b in after and b not in before,
                'Rename hint does not match Git before/after snapshots')
        changes.append({'change':'rename','scope':scope,'oldName':a,'name':b,
                        'payload':after[b]['payload'],'columns':column_changes(before[a]['payload'],after[b]['payload']),
                        'semantics':'upsert-new-name-and-soft-delete-old-name; no OM metadata migration'})
        remaining_old.remove(a);remaining_new.remove(b)
    for name in sorted(remaining_new-remaining_old):
        changes.append({'change':'create','scope':scope,'name':name,'payload':after[name]['payload'],
                        'columns':column_changes({},after[name]['payload'])})
    for name in sorted(remaining_old & remaining_new):
        if before[name]['canonicalDDL']!=after[name]['canonicalDDL']:
            changes.append({'change':'update','scope':scope,'name':name,'payload':after[name]['payload'],
                            'columns':column_changes(before[name]['payload'],after[name]['payload'])})
    for name in sorted(remaining_old-remaining_new):
        changes.append({'change':'drop','scope':scope,'name':name})
    return changes


def operations(changes):
    """Each body is a standard OM body; the surrounding array is a CI request manifest."""
    upserts,patches,deletes=[],[],[]
    for change in changes:
        if change['change']!='drop':
            full=deepcopy(change['payload'])
            initial=deepcopy(full)
            initial['tableConstraints']=[c for c in full.get('tableConstraints',[]) if c['constraintType']!='FOREIGN_KEY']
            upserts.append({'method':'PUT','path':'/api/v1/tables','query':{},
                            'contentType':'application/json','body':initial,
                            'tableFqn':change['scope']+'.'+fqn(change['name'])})
            # PATCH by FQN enforces the complete Git structure/comments, avoiding PUT's
            # Bot-specific preservation of old descriptions. No ID lookup/OM read needed.
            fields={k:full[k] for k in ('columns','tableConstraints','schemaDefinition','tableType')}
            fields['description']=full.get('description')
            fields['tags']=full.get('tags',[])
            for column in fields['columns']:
                column.setdefault('description',None)
                column.setdefault('tags',[])
            patches.append({'method':'PATCH','path':'/api/v1/tables/name/'+quote(change['scope']+'.'+fqn(change['name']),safe=''),
                            'query':{},'contentType':'application/json-patch+json',
                            'body':[{'op':'add','path':'/'+key,'value':value} for key,value in fields.items()],
                            'tableFqn':change['scope']+'.'+fqn(change['name'])})
        if change['change'] in {'drop','rename'}:
            name=change.get('oldName',change['name'])
            identity=change['scope']+'.'+fqn(name)
            deletes.append({'method':'DELETE','path':'/api/v1/tables/name/'+quote(identity,safe=''),
                            'contentType':'application/json','query':{'hardDelete':'false','recursive':'true'},
                            'tableFqn':identity})
    return upserts+patches+deletes


def generate(repo_path,base_ref,head_ref,config, *, comparison='merge-base',renames=None,mode='diff',
             security_classification='Security'):
    require(comparison in {'merge-base','direct'},'Unknown comparison mode')
    require(mode in {'diff','full'},'Unknown mode')
    require(mode=='full' or base_ref,'--base is required in diff mode')
    require(mode=='diff' or not renames,'Rename hints are only meaningful in diff mode')
    repo=GitRepository(repo_path)
    head=repo.commit(head_ref)
    base=repo.commit(base_ref) if mode=='diff' else None
    start=(repo.run('merge-base',base,head).decode().strip() if comparison=='merge-base' else base) if base else None
    paths,groups=load_config(config)
    changed=repo.changed(start,head) if mode=='diff' else repo.paths(head)
    unconfigured={p for p in changed if PurePosixPath(p).name=='schemas.sql' and p not in paths}
    require(not unconfigured,'Changed schemas.sql paths missing configuration: '+', '.join(sorted(unconfigured)))
    hints=renames or {'tableRenames':[]}
    require(set(hints)=={'tableRenames'} and isinstance(hints['tableRenames'],list),'Invalid rename manifest')
    selected={paths[p] for p in changed if p in paths} if mode=='diff' else set(groups)
    require(all(r.get('schemaFqn') in selected for r in hints['tableRenames']),
            'Rename hint refers to a scope with no changed configured files')
    changes,reports,sources=[],[],[]
    for scope in sorted(selected):
        group=groups[scope]
        before,old_warnings,old_files=collect(repo,start,group,security_classification) if mode=='diff' else ({},[],[])
        after,new_warnings,new_files=collect(repo,head,group,security_classification)
        require(mode=='diff' or any(f['present'] for f in new_files),
                'Full mode: every configured scope must have a schema file at head: '+scope)
        # Validate same-schema FK targets against the COMPLETE new Git snapshot.
        prefix=scope+'.'
        valid={prefix+fqn(t,c['name']) for t,v in after.items() for c in v['payload']['columns']}
        for table in after.values():
            for constraint in table['payload'].get('tableConstraints',[]):
                for reference in constraint.get('referredColumns',[]) or []:
                    if reference.startswith(prefix):
                        require(reference in valid,'Final Git snapshot has a dangling foreign key: '+reference)
        scope_changes=compare(before,after,scope,hints['tableRenames'])
        if mode=='full':
            for change in scope_changes:
                change['change']='upsert'
        changes.extend(scope_changes)
        reports.extend([{'side':'base',**w} for w in old_warnings]+[{'side':'head',**w} for w in new_warnings])
        sources.append({'scope':scope,'before':old_files,'after':new_files})
    result={'formatVersion':1,'sourceOfTruth':'git','mode':mode,
            'comparison':comparison if mode=='diff' else None,
            'baseCommit':base,'comparisonBaseCommit':start,'headCommit':head,
            'configHash':digest(config),'securityClassification':security_classification,
            'changedPaths':sorted(changed) if mode=='diff' else [],
            'inputPaths':sorted(p for p in changed if p in paths),
            'sources':sources,'changes':changes,'requests':operations(changes),'warnings':reports,
            'counts':{kind:sum(c['change']==kind for c in changes) for kind in ('create','update','drop','rename','upsert')},
            'limitations':['No OM reads, drift detection or annotation migration.',
                           'Table/column renames are not inferred from similarity.',
                           'Requests are not a transaction; serialize publication by DB and commit order.',
                           'Parent service/database/schema must already exist.']}
    result['artifactHash']=digest(result)
    return result


def write_output(directory,result):
    directory=Path(directory)
    require(not directory.exists(),'Output directory already exists; choose a new path to avoid stale artifacts')
    directory.mkdir(parents=True)
    (directory/'om-requests.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (directory/'upserts.json').write_text(json.dumps([c['payload'] for c in result['changes'] if c['change']!='drop'],
                                                   ensure_ascii=False,indent=2)+'\n')
    # upserts.json is the FINAL standard CreateTableRequest array, NOT a mixed change envelope.
    for i,request in enumerate(result['requests']):
        if 'body' in request:
            (directory/f'{i:03d}-{request["method"].lower()}.json').write_text(
                json.dumps(request['body'],ensure_ascii=False,indent=2)+'\n')
    lines=['# Git → OM change report','',f'Base: `{result["comparisonBaseCommit"]}`',
           f'Head: `{result["headCommit"]}`','', '| Change | Schema | Table |','|---|---|---|']
    for c in result['changes']:
        name=(c['oldName']+' → ' if 'oldName' in c else '')+c['name']
        lines.append(f'| {c["change"]} | {c["scope"]} | {name} |')
    if not result['changes']:lines.append('| none | | |')
    (directory/'summary.md').write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['diff','full'],default='diff')
    parser.add_argument('--repo',type=Path,default=Path('.'))
    parser.add_argument('--base')
    parser.add_argument('--head',required=True)
    parser.add_argument('--comparison',choices=['merge-base','direct'],default='merge-base')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--renames',type=Path)
    parser.add_argument('--security-classification',default='Security')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        config=json.loads(args.config.read_text(encoding='utf-8'))
        hints=json.loads(args.renames.read_text(encoding='utf-8')) if args.renames else None
        require(args.mode=='diff' or not args.base,'Full mode does not use --base')
        result=generate(args.repo,args.base,args.head,config,comparison=args.comparison,renames=hints,
                        mode=args.mode,security_classification=args.security_classification)
        write_output(args.output,result)
        print(json.dumps({'counts':result['counts'],'requests':len(result['requests']),
                          'headCommit':result['headCommit'],'output':str(args.output)},ensure_ascii=False))
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
