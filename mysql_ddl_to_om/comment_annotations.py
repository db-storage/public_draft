"""Explicit @om directives in MySQL table/column COMMENT literals."""
from __future__ import annotations
import re


def extract(description: str, security_classification='Security'):
    from mysql_ddl_to_om import ConversionError, fqn
    prose,tags,security=[],{},None
    for line in description.splitlines():
        stripped=line.strip()
        if '@om.' not in stripped:
            prose.append(line)
            continue
        match=re.fullmatch(r'@om\.(security|tag)\s*=\s*(.+)',stripped)
        if not match:
            raise ConversionError('Unknown/malformed @om directive; use a separate line: '+stripped)
        kind,value=match.groups();value=value.strip()
        if not value or any(ord(c)<32 for c in value):
            raise ConversionError('Invalid annotation value')
        if kind=='security':
            if security is not None and security!=value:
                raise ConversionError('Conflicting @om.security levels')
            if '.' in value:
                raise ConversionError('@om.security must be a single level name')
            security=value
            tag=fqn(security_classification,value)
        else:
            if '.' not in value:
                raise ConversionError('@om.tag requires an exact Classification.Tag FQN')
            tag=value
        tags[tag]={'tagFQN':tag,'source':'Classification','labelType':'Manual','state':'Confirmed'}
    return '\n'.join(prose).strip(),[tags[k] for k in sorted(tags)]


def apply_to_request(request,security_classification='Security'):
    """In place; original complete COMMENT remains in schemaDefinition."""
    for entity in [request,*request['columns']]:
        if 'description' not in entity:
            continue
        description,tags=extract(entity['description'],security_classification)
        entity['description']=description
        if tags:
            entity['tags']=tags
    return request
