#!/usr/bin/env python3
"""Plan/apply a complete single-schema MySQL snapshot to OpenMetadata.

Table rename is an explicit metadata-copy + soft-delete operation, NOT a native
OM identity-preserving rename. No production database connection is used.
"""
from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mysql_ddl_to_om import ConversionError, fqn

FIELDS = 'columns,tableConstraints,schemaDefinition,tags,owners,domains,extension'
TABLE_ANNOTATIONS = ('description', 'displayName', 'tags', 'owners', 'domains', 'extension')
COLUMN_ANNOTATIONS = ('description', 'displayName', 'tags')
STRUCTURE = ('columns', 'tableConstraints', 'schemaDefinition', 'tableType')
LIMITATIONS = [
    'Table rename creates/restores a target entity and soft-deletes the source; target ID differs.',
    'Column rename copies selected annotations and replaces column names; lineage continuity is not guaranteed.',
    'Lineage, tests, profiles, usage, historical versions and column extensions are not migrated.',
    'Apply is multi-request, not transactional. Serialize jobs for this schema; replan after partial failure.',
]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def require(condition, message):
    if not condition:
        raise ConversionError(message)


def canonical(value):
    """Ignore null/empty server defaults and read-only annotation attributes."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()
                if v is not None and v != [] and v != {} and k not in {'href', 'inherited', 'appliedBy'}}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def table_guard(entity):
    return canonical({k: entity.get(k) for k in (
        'id', 'name', 'fullyQualifiedName', 'version', 'updatedAt', 'deleted',
        *STRUCTURE, *TABLE_ANNOTATIONS)})


def baseline(tables):
    return {t['name']: table_guard(t) for t in sorted(tables, key=lambda t: t['name'])}


def constraints_equal(a, b):
    def normalise(items):
        result=[]
        for item in items or []:
            row=canonical(item)
            # OM treats constraint column lists as sets and may reorder them.
            for key in ('columns','referredColumns'):
                if key in row:
                    row[key]=sorted(row[key])
            result.append(row)
        return sorted(result,key=digest)
    return normalise(a)==normalise(b)


def metadata_equal(key, a, b):
    if key in {'owners', 'domains'}:
        def refs(value):
            return sorted(({'id':r['id'],'type':r['type']} for r in value or []), key=digest)
        return refs(a)==refs(b)
    return canonical(a)==canonical(b)


def split_fqn(value):
    return next(csv.reader([value], delimiter='.', quotechar='"', strict=True))


def column_projection(column):
    keys = ('name', 'dataType', 'dataTypeDisplay', 'dataLength', 'precision', 'scale',
            'constraint', 'ordinalPosition', *COLUMN_ANNOTATIONS)
    result=canonical({k: column[k] for k in keys if k in column})
    # OM DatabaseUtil lowercases this field, including ENUM/SET display text.
    if result.get('dataTypeDisplay'):
        result['dataTypeDisplay']=result['dataTypeDisplay'].lower()
    return result


def column_diff(old, new, renames):
    oldmap = {c['name']: column_projection(c) for c in old}
    newmap = {c['name']: column_projection(c) for c in new}
    return {
        'added': sorted(newmap.keys() - oldmap.keys() - set(renames.values())),
        'removed': sorted(oldmap.keys() - newmap.keys() - set(renames)),
        'renamed': [{'from': a, 'to': b} for a, b in sorted(renames.items())],
        'modified': sorted(n for n in oldmap.keys() & newmap.keys() if oldmap[n] != newmap[n]),
    }


class OMClient:
    def __init__(self, url, token, allow_http=False):
        parsed = urlsplit(url)
        require(parsed.scheme in {'http','https'} and parsed.netloc and not parsed.query
                and not parsed.fragment and not parsed.username and not parsed.password,
                'Invalid OM URL')
        require(parsed.scheme == 'https' or allow_http, 'HTTP requires --allow-http')
        require(token, 'OM_TOKEN is required')
        self.base = url.rstrip('/')
        if not self.base.endswith('/api'):
            self.base += '/api'
        self.session = requests.Session()
        # Never automatically replay PATCH/POST/DELETE/restore after an ambiguous timeout.
        retry = Retry(total=3, backoff_factor=.5, status_forcelist=[429,500,502,503,504],
                      allowed_methods=frozenset({'GET'}), respect_retry_after_header=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({'Authorization': 'Bearer '+token})

    def close(self):
        self.session.close()

    def request(self, method, path, *, body=None, params=None, missing=False, patch=False):
        headers = {'Content-Type': 'application/json-patch+json' if patch else 'application/json'}
        response = self.session.request(method, self.base + path, json=body, params=params,
                                        headers=headers, timeout=(10,60), allow_redirects=False)
        if response.status_code == 404 and missing:
            return None
        require(response.status_code in {200,201,204},
                f'{method} {path}: HTTP {response.status_code}; stop and generate a fresh plan')
        return response.json() if response.content else None

    def parent(self, scope):
        return self.request('GET', '/v1/databaseSchemas/name/'+quote(scope, safe=''))

    def list_tables(self, scope):
        tables, cursor, seen_cursors, seen_ids = [], None, set(), set()
        while True:
            params = {'databaseSchema':scope, 'fields':FIELDS, 'include':'all', 'limit':100}
            if cursor:
                params['after'] = cursor
            result = self.request('GET','/v1/tables',params=params)
            require(isinstance(result,dict) and isinstance(result.get('data'),list), 'Invalid list response')
            for table in result['data']:
                require(table.get('databaseSchema',{}).get('fullyQualifiedName') == scope,
                        'Server returned a table outside the exact schema scope')
                require(table.get('id') and table.get('name') and table.get('version') is not None,
                        'List response missing table ID/name/version')
                require(isinstance(table.get('columns'),list), 'List response missing full columns')
                require(table['id'] not in seen_ids, 'Duplicate table while paginating; replan')
                require(len(table.get('columns',[])) == len({c['name'] for c in table.get('columns',[])}),
                        'Duplicate column names in OM')
                seen_ids.add(table['id'])
                tables.append(table)
            cursor = result.get('paging',{}).get('after')
            if not cursor:
                break
            require(cursor not in seen_cursors, 'Repeated pagination cursor')
            seen_cursors.add(cursor)
        require(len(tables) == len({t['name'] for t in tables}), 'Duplicate table names in OM scope')
        return tables

    def get(self, identity):
        return self.request('GET','/v1/tables/'+quote(identity, safe=''),
                            params={'fields':FIELDS,'include':'all'})

    def by_name(self, name):
        return self.request('GET','/v1/tables/name/'+quote(name, safe=''),
                            params={'fields':FIELDS,'include':'all'}, missing=True)

    def create(self, payload):
        return self.request('POST','/v1/tables',body=payload)

    def restore(self, identity):
        return self.request('PUT','/v1/tables/restore',body={'id':identity})

    def patch(self, current, changes):
        require(current.get('version') is not None, 'Cannot patch entity without version')
        operations = [{'op':'test','path':'/version','value':current['version']},
                      {'op':'test','path':'/name','value':current['name']}]
        operations += [{'op':'add','path':'/'+key,'value':value} for key,value in changes.items()]
        return self.request('PATCH','/v1/tables/'+quote(current['id'],safe=''),
                            body=operations,patch=True)

    def delete(self, identity):
        return self.request('DELETE','/v1/tables/'+quote(identity,safe=''),
                            params={'hardDelete':'false','recursive':'true'})


def annotations(entity, fields):
    result = {k: deepcopy(entity[k]) for k in fields if entity.get(k) is not None}
    # Only keep references accepted by create APIs.
    for key in ('owners','domains'):
        if key in result:
            result[key] = [{k:v for k,v in ref.items() if k in {'id','type'}} for ref in result[key]]
    for tag in result.get('tags',[]):
        for key in ('appliedBy','inherited','href'):
            tag.pop(key,None)
    return result


def merge_payload(desired, existing, column_renames, copy_table=False):
    payload = deepcopy(desired)
    if copy_table:
        payload = {**annotations(existing,TABLE_ANNOTATIONS), **payload}
    columns = {c['name']:c for c in existing.get('columns',[])}
    inverse = {new:old for old,new in column_renames.items()}
    for i, col in enumerate(payload['columns']):
        source = columns.get(inverse.get(col['name'],col['name']), {})
        payload['columns'][i] = {**annotations(source,COLUMN_ANNOTATIONS), **col}
    return payload


def validate_renames(raw, desired, current, *, resume=False):
    require(set(raw) <= {'tableRenames','columnRenames'}, 'Unknown rename manifest keys')
    tables, columns = {}, {}
    for row in raw.get('tableRenames',[]):
        require(isinstance(row,dict) and set(row)=={'from','to'}, 'Invalid table rename entry')
        a,b = row['from'],row['to']
        require(isinstance(a,str) and isinstance(b,str) and a and b and a!=b, 'Invalid rename names')
        require(a not in tables and b not in tables.values(), 'Duplicate table rename source/target')
        tables[a]=b
    require(not (set(tables) & set(tables.values())), 'Rename chains/swaps must use separate snapshots')
    for a,b in tables.items():
        require(a not in desired and b in desired, 'Rename manifest must match the final full snapshot')
        require(a in current or b in current, 'Rename source and target are both absent')
        if a in current and not current[a].get('deleted'):
            require(not (b in current and not current[b].get('deleted')) or resume,
                    'Both rename names are active; only after partial apply use --resume-renames')
    for row in raw.get('columnRenames',[]):
        require(isinstance(row,dict) and set(row)=={'table','from','to'}, 'Invalid column rename entry')
        table,a,b = row['table'],row['from'],row['to']
        require(all(isinstance(x,str) and x for x in (table,a,b)) and a!=b, 'Invalid column rename names')
        require(table in desired, 'Column rename table must be the final table name')
        mapping = columns.setdefault(table,{})
        require(a not in mapping and b not in mapping.values(), 'Duplicate column rename source/target')
        mapping[a]=b
    inverse_tables={b:a for a,b in tables.items()}
    effective_columns={}
    for table,mapping in columns.items():
        require(not (set(mapping)&set(mapping.values())), 'Column rename chains/swaps are unsupported')
        source_name=inverse_tables.get(table,table)
        source=current.get(source_name)
        donor=source if source and not source.get('deleted') else current.get(table)
        donor=donor or source
        require(donor is not None, 'Column rename source table missing')
        old={c['name'] for c in donor.get('columns',[])}
        new={c['name'] for c in desired[table]['columns']}
        effective_columns[table]={}
        for a,b in mapping.items():
            require(a not in new and b in new, 'Column rename does not match final snapshot')
            require(not (a in old and b in old), 'Column rename target already exists')
            if a in old:
                effective_columns[table][a]=b
            else:
                require(b in old, 'Column rename source and target missing')
    return tables,effective_columns


def make_plan(bundle, current, parent, *, renames=None, exclusive=False,
              allow_empty=False, max_deletes=10, max_delete_ratio=.5, resume=False):
    require(exclusive, 'Declare --exclusive-schema: this snapshot owns ALL tables in this OM schema')
    require(bundle.get('formatVersion')==1 and bundle.get('scope'),
            'Reconvert with the new converter: explicit scope is required')
    require(isinstance(bundle.get('tables'),list), 'Invalid tables array')
    scope = bundle['scope']
    require(scope['fqn']==fqn(scope['service'],scope['database'],scope['schema']), 'Invalid scope FQN')
    require(parent.get('id') and parent.get('fullyQualifiedName')==scope['fqn'], 'Wrong parent schema')
    desired={t['name']:t for t in bundle['tables']}
    require(len(desired)==len(bundle['tables']), 'Duplicate desired table names')
    require(desired or allow_empty, 'Empty snapshot requires --allow-empty at planning time')
    for t in desired.values():
        require(t.get('databaseSchema')==scope['fqn'], 'Table outside declared scope')
        require(t.get('columns') and len(t['columns'])==len({c['name'] for c in t['columns']}),
                'Invalid or duplicate desired columns')
    require(all(t.get('databaseSchema',{}).get('fullyQualifiedName')==scope['fqn'] for t in current),
            'Existing table outside scope')
    existing={t['name']:t for t in current}
    require(len(existing)==len(current), 'Duplicate current table names')
    table_renames,column_renames=validate_renames(renames or {},desired,existing,resume=resume)
    inverse={b:a for a,b in table_renames.items()}
    targets=[]
    for name,request in sorted(desired.items()):
        target=existing.get(name)
        source=existing.get(inverse.get(name,''))
        # On a partial rename resume, source annotations remain authoritative until deleted.
        donor=source if source and not source.get('deleted') else target
        donor=donor or source or {}
        mappings=column_renames.get(name,{})
        payload=merge_payload(request,donor,mappings,copy_table=bool(source and donor is source))
        action='create' if target is None else ('restore' if target.get('deleted') else 'update')
        targets.append({'name':name,'action':action,'sourceName':inverse.get(name),
                        'payload':payload,
                        'columnChanges':column_diff(donor.get('columns',[]),payload['columns'],mappings)})
    for target in targets:
        for constraint in target['payload'].get('tableConstraints',[]):
            for reference in constraint.get('referredColumns',[]) or []:
                parts=split_fqn(reference)
                require(len(parts)==5, 'Invalid referred column FQN')
                if fqn(*parts[:3])==scope['fqn']:
                    require(parts[3] in desired and any(c['name']==parts[4]
                            for c in desired[parts[3]]['columns']),
                            'Foreign key refers to a missing table/column in final snapshot')
    removed=[{'name':n,'id':t['id'],'reason':'rename' if n in table_renames else 'absent_from_snapshot'}
             for n,t in sorted(existing.items()) if n not in desired and not t.get('deleted')]
    active_count=sum(not t.get('deleted',False) for t in current)
    normal=[r for r in removed if r['reason']!='rename']
    require(max_deletes>=0 and 0<=max_delete_ratio<=1, 'Invalid deletion thresholds')
    require(len(normal)<=max_deletes, 'Deletion count exceeds --max-deletes')
    require(not active_count or len(normal)/active_count<=max_delete_ratio,
            'Deletion ratio exceeds --max-delete-ratio')
    plan={'planVersion':1,'scope':scope,'parentId':parent['id'],'exclusiveSchema':True,
          'bundleHash':digest(bundle),'sources':bundle.get('sources',[]),
          'baseline':baseline(current),'targets':targets,'softDeletes':removed,
          'warnings':bundle.get('warnings',[]),'limitations':LIMITATIONS}
    plan['planHash']=digest(plan)
    return plan


def validate_plan(plan):
    require(plan.get('planVersion')==1 and plan.get('exclusiveSchema') is True, 'Invalid plan')
    hashed={k:v for k,v in plan.items() if k!='planHash'}
    require(plan.get('planHash')==digest(hashed), 'Plan hash mismatch; regenerate instead of editing')
    scope=plan['scope']
    require(scope['fqn']==fqn(scope['service'],scope['database'],scope['schema']), 'Invalid scope')
    ids={v['id'] for v in plan['baseline'].values()}
    names=set()
    for target in plan['targets']:
        require(target['name'] not in names, 'Duplicate target')
        names.add(target['name'])
        require(target['payload']['databaseSchema']==scope['fqn'] and
                target['payload']['name']==target['name'], 'Target outside scope')
    for row in plan['softDeletes']:
        require(row['name'] in plan['baseline'] and row['id'] in ids and
                plan['baseline'][row['name']]['id']==row['id'] and row['name'] not in names,
                'Invalid soft delete')


def structural_changes(current,payload, *, link=False):
    if link:
        wanted=payload.get('tableConstraints',[])
        return {} if constraints_equal(current.get('tableConstraints'),wanted) else {'tableConstraints':wanted}
    changes={}
    if [column_projection(c) for c in current.get('columns',[])] != [
            column_projection(c) for c in payload['columns']]:
        changes['columns']=payload['columns']
    for key in ('schemaDefinition','tableType',*TABLE_ANNOTATIONS):
        if key in payload and not metadata_equal(key,current.get(key),payload[key]):
            changes[key]=payload[key]
    # Preserve FK when local columns and constraints are unchanged. Otherwise replace
    # constraints atomically with columns before final cross-table FK pass.
    no_fk=[c for c in payload.get('tableConstraints',[]) if c['constraintType']!='FOREIGN_KEY']
    local_current=[c for c in current.get('tableConstraints') or [] if c['constraintType']!='FOREIGN_KEY']
    if 'columns' in changes or not constraints_equal(local_current,no_fk):
        changes['tableConstraints']=no_fk
    return changes


def apply_plan(client,plan, *, acknowledge_rename=False, journal_path=None):
    validate_plan(plan)
    require(not any(t.get('sourceName') for t in plan['targets']) or acknowledge_rename,
            'Table rename changes entity ID; pass --acknowledge-rename-replacement')
    scope=plan['scope']['fqn']
    require(client.parent(scope)['id']==plan['parentId'], 'Parent schema ID changed; replan')
    require(baseline(client.list_tables(scope))==plan['baseline'], 'OM changed after planning; replan')
    # Cross-schema referenced columns cannot be validated from this snapshot.
    for target in plan['targets']:
        for constraint in target['payload'].get('tableConstraints',[]):
            for reference in constraint.get('referredColumns',[]) or []:
                parts=split_fqn(reference)
                if fqn(*parts[:3])!=scope:
                    remote=client.by_name(fqn(*parts[:4]))
                    require(remote and not remote.get('deleted') and any(
                            c['name']==parts[4] for c in remote['columns']),
                            'External foreign key target is absent; no writes performed')
    journal={'planHash':plan['planHash'],'completed':[],'status':'running'}
    def log(kind,name):
        journal['completed'].append({'phase':kind,'table':name})
        if journal_path:
            write_json(journal_path,journal)
    if journal_path:
        write_json(journal_path,journal)
    try:
        expected={}
        # 1. Create/restore every desired name without FK dependencies.
        for target in plan['targets']:
            name=target['name']
            if target['action']=='create':
                request=deepcopy(target['payload'])
                request['tableConstraints']=[c for c in request.get('tableConstraints',[]) if c['constraintType']!='FOREIGN_KEY']
                entity=client.create(request)
                require(entity and entity.get('id'), 'Create response missing ID')
                log('create',name)
            elif target['action']=='restore':
                client.restore(plan['baseline'][name]['id'])
                log('restore',name)
        # 2. Apply all local structures, preserving supported annotations.
        for target in plan['targets']:
            current=client.by_name(scope+'.'+fqn(target['name']))
            require(current and not current.get('deleted'), 'Target missing after create/restore')
            if target['name'] in plan['baseline']:
                require(current['id']==plan['baseline'][target['name']]['id'], 'Target ID changed')
                if target['action']=='update':
                    require(table_guard(current)==plan['baseline'][target['name']],
                            'Target changed during apply; replan')
                elif target['action']=='restore':
                    before=deepcopy(plan['baseline'][target['name']])
                    after=table_guard(current)
                    for key in ('version','updatedAt','deleted'):
                        before.pop(key,None)
                        after.pop(key,None)
                    require(before==after, 'Restored target metadata changed; replan')
            changes=structural_changes(current,target['payload'])
            if changes:
                client.patch(current,changes)
                log('structure',target['name'])
                current=client.get(current['id'])
            expected[target['name']]=table_guard(current)
        # 3. With all columns present, attach FK constraints (including cycles).
        for target in plan['targets']:
            current=client.by_name(scope+'.'+fqn(target['name']))
            require(table_guard(current)==expected[target['name']],
                    'Target changed before constraints update; replan')
            changes=structural_changes(current,target['payload'],link=True)
            if changes:
                client.patch(current,changes)
                log('constraints',target['name'])
                current=client.get(current['id'])
            expected[target['name']]=table_guard(current)
        # 4. Verify writes before removing old names.
        for target in plan['targets']:
            current=client.by_name(scope+'.'+fqn(target['name']))
            require(current and not current.get('deleted'), 'Target verification failed')
            require(table_guard(current)==expected[target['name']],
                    'Target changed before verification; replan')
            require(not structural_changes(current,target['payload']) and
                    not structural_changes(current,target['payload'],link=True),
                    f'Server did not persist target schema: {target["name"]}')
        # 5. Only soft-delete missing/renamed sources, never hard-delete.
        for row in plan['softDeletes']:
            current=client.get(row['id'])
            require(table_guard(current)==plan['baseline'][row['name']],
                    'Delete source changed during apply; replan')
            client.delete(row['id'])
            require(client.get(row['id']).get('deleted') is True, 'Soft-delete verification failed')
            log('soft_delete',row['name'])
        journal['status']='succeeded'
    except Exception:
        journal['status']='failed_replan_required'
        if journal_path:
            write_json(journal_path,journal)
        raise
    if journal_path:
        write_json(journal_path,journal)
    return journal


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    plan=subs.add_parser('plan',help='Read OM; generate a reviewable plan without writes')
    plan.add_argument('bundle',type=Path)
    plan.add_argument('--renames',type=Path,help='JSON with tableRenames/columnRenames')
    plan.add_argument('--output',type=Path,required=True)
    plan.add_argument('--exclusive-schema',action='store_true')
    plan.add_argument('--allow-empty',action='store_true')
    plan.add_argument('--max-deletes',type=int,default=10)
    plan.add_argument('--max-delete-ratio',type=float,default=.5)
    plan.add_argument('--resume-renames',action='store_true')
    apply=subs.add_parser('apply',help='Execute exactly the generated plan')
    apply.add_argument('plan',type=Path)
    apply.add_argument('--journal',type=Path,required=True)
    apply.add_argument('--acknowledge-rename-replacement',action='store_true')
    for sub in (plan,apply):
        sub.add_argument('--url',default=os.getenv('OM_URL'))
        sub.add_argument('--allow-http',action='store_true')
    args=parser.parse_args(argv)
    client=None
    try:
        require(args.url,'--url or OM_URL is required')
        client=OMClient(args.url,os.getenv('OM_TOKEN',''),args.allow_http)
        if args.command=='plan':
            bundle=json.loads(args.bundle.read_text())
            require(bundle.get('scope'), 'Reconvert to produce an explicit scope')
            scope=bundle['scope']['fqn']
            parent=client.parent(scope)
            current=client.list_tables(scope)
            renames=json.loads(args.renames.read_text()) if args.renames else {}
            result=make_plan(bundle,current,parent,renames=renames,exclusive=args.exclusive_schema,
                             allow_empty=args.allow_empty,max_deletes=args.max_deletes,
                             max_delete_ratio=args.max_delete_ratio,resume=args.resume_renames)
            write_json(args.output,result)
            print(json.dumps({'targets':[{k:t[k] for k in ('name','action','sourceName','columnChanges')}
                                        for t in result['targets']], 'softDeletes':result['softDeletes'],
                              'limitations':result['limitations']},ensure_ascii=False,indent=2))
        else:
            plan=json.loads(args.plan.read_text())
            print(json.dumps(apply_plan(client,plan,acknowledge_rename=args.acknowledge_rename_replacement,
                                        journal_path=args.journal),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
