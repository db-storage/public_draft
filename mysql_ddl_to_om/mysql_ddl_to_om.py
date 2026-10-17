#!/usr/bin/env python3
"""MySQL CREATE TABLE snapshots -> OpenMetadata CreateTableRequest JSON.

No database connection is used. SQLGlot is a parser, not a MySQL validator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError


class ConversionError(ValueError):
    pass


# OM 1.12 table.json enum. Unsigned is retained in dataTypeDisplay.
TYPE_MAP = {
    'TINYINT': 'TINYINT', 'SMALLINT': 'SMALLINT', 'MEDIUMINT': 'INT',
    'INT': 'INT', 'BIGINT': 'BIGINT', 'UTINYINT': 'TINYINT',
    'USMALLINT': 'SMALLINT', 'UMEDIUMINT': 'INT', 'UINT': 'INT',
    'UBIGINT': 'BIGINT', 'FLOAT': 'FLOAT', 'DOUBLE': 'DOUBLE',
    'DECIMAL': 'DECIMAL', 'UDECIMAL': 'DECIMAL', 'BOOLEAN': 'BOOLEAN',
    'CHAR': 'CHAR', 'NCHAR': 'CHAR', 'VARCHAR': 'VARCHAR', 'NVARCHAR': 'VARCHAR',
    'TEXT': 'TEXT', 'TINYTEXT': 'TEXT', 'MEDIUMTEXT': 'MEDIUMTEXT',
    'LONGTEXT': 'TEXT', 'BINARY': 'BINARY', 'VARBINARY': 'VARBINARY',
    'BLOB': 'BLOB', 'TINYBLOB': 'BLOB', 'MEDIUMBLOB': 'MEDIUMBLOB',
    'LONGBLOB': 'LONGBLOB', 'DATE': 'DATE', 'TIME': 'TIME',
    # SQLGlot uses TIMESTAMPTZ internally for MySQL TIMESTAMP.
    'TIMESTAMPTZ': 'TIMESTAMP', 'TIMESTAMP': 'TIMESTAMP', 'DATETIME': 'DATETIME',
    'YEAR': 'YEAR', 'BIT': 'BIT', 'ENUM': 'ENUM', 'SET': 'SET', 'JSON': 'JSON',
}


def fqn(*parts: str) -> str:
    """OM quotes segments containing dots. Reject embedded quote/control chars."""
    def segment(s):
        if not s or '"' in s or any(ord(c) < 32 for c in s):
            raise ConversionError(f'Unsupported FQN segment: {s!r}')
        return f'"{s}"' if '.' in s else s
    return '.'.join(segment(s) for s in parts)


def plain_columns(nodes) -> list[str]:
    names = []
    for node in nodes:
        if isinstance(node, exp.Identifier):
            names.append(node.name)
        elif isinstance(node, exp.Column) and not node.table:
            names.append(node.name)
        else:
            raise ConversionError('Expression/prefix index cannot be mapped as a plain constraint: '
                                  + node.sql(dialect='mysql'))
    if not names or len(set(n.casefold() for n in names)) != len(names):
        raise ConversionError('Empty or duplicate constraint columns')
    return names


def column_request(node: exp.ColumnDef, position: int, warn) -> tuple[dict, list[dict]]:
    dtype = node.args.get('kind')
    if not isinstance(dtype, exp.DataType) or dtype.this.name not in TYPE_MAP:
        raise ConversionError(f'Unsupported type for {node.name}: {dtype}')
    kind = dtype.this.name
    result = {'name': node.name, 'dataType': TYPE_MAP[kind],
              'dataTypeDisplay': dtype.sql(dialect='mysql'), 'ordinalPosition': position}
    params = dtype.expressions
    if kind in {'CHAR', 'NCHAR', 'VARCHAR', 'NVARCHAR', 'BINARY', 'VARBINARY'}:
        if len(params) == 1 and params[0].name.isdigit():
            result['dataLength'] = int(params[0].name)
        elif params:
            raise ConversionError(f'Invalid length: {dtype}')
        elif kind in {'CHAR','NCHAR','BINARY'}:
            result['dataLength'] = 1
        else:
            raise ConversionError(f'Missing required length: {dtype}')
    if kind in {'DECIMAL', 'UDECIMAL', 'FLOAT', 'DOUBLE'} and params:
        if len(params) > 2 or not all(p.name.isdigit() for p in params):
            raise ConversionError(f'Invalid precision/scale: {dtype}')
        result['precision'] = int(params[0].name)
        if len(params) > 1:
            result['scale'] = int(params[1].name)
        if result['precision'] <= 0 or result.get('scale',0) > result['precision']:
            raise ConversionError(f'Invalid precision/scale: {dtype}')
    # One OM column.constraint slot cannot encode every combination.
    # Keep PK and UNIQUE additionally in tableConstraints.
    not_null, pk, unique = False, False, False
    for wrapper in node.args.get('constraints') or []:
        constraint = wrapper.args.get('kind')
        name = type(constraint).__name__
        if name == 'NotNullColumnConstraint':
            not_null = not constraint.args.get('allow_null', False)
        elif name == 'PrimaryKeyColumnConstraint':
            pk = True
        elif name == 'UniqueColumnConstraint':
            unique = True
        elif name == 'CommentColumnConstraint':
            if not isinstance(constraint.this, exp.Literal) or not constraint.this.is_string:
                raise ConversionError('Non-literal column comment')
            result['description'] = constraint.this.this
        elif name in {'DefaultColumnConstraint', 'AutoIncrementColumnConstraint',
                      'OnUpdateColumnConstraint', 'ComputedColumnConstraint',
                      'CollateColumnConstraint', 'CharacterSetColumnConstraint',
                      'CheckColumnConstraint'}:
            warn(f'{node.name}: {name} retained in schemaDefinition only')
        else:
            raise ConversionError(f'{node.name}: unsupported column constraint {name}')
    if pk:
        result['constraint'] = 'NOT_NULL'
    elif not_null:
        result['constraint'] = 'NOT_NULL'
    else:
        result['constraint'] = 'NULL'
    table_constraints = []
    if pk:
        table_constraints.append({'constraintType': 'PRIMARY_KEY', 'columns': [node.name]})
    if unique:
        table_constraints.append({'constraintType': 'UNIQUE', 'columns': [node.name]})
    return result, table_constraints


def convert_sql(sql: str, *, service: str, database: str, schema: str,
                origin: str = '<string>', allow_empty: bool = False,
                security_classification: str = 'Security') -> tuple[list[dict], list[dict]]:
    """Return standard create-table requests and an explicit metadata-loss report."""
    # MySQL executable comments are not ordinary comments. Do not silently discard them.
    if '/*!' in sql:
        raise ConversionError(f'{origin}: MySQL executable comments are unsupported')
    try:
        statements = sqlglot.parse(sql, read='mysql', error_level=ErrorLevel.RAISE)
    except ParseError as exc:
        raise ConversionError(f'{origin}: {exc}') from exc
    statements = [s for s in statements if s is not None and not isinstance(s, exp.Semicolon)]
    if not statements:
        if allow_empty:
            return [], []
        raise ConversionError(f'{origin}: no CREATE TABLE found')
    tables, warnings = [], []
    for stmt in statements:
        if not isinstance(stmt, exp.Create) or stmt.args.get('kind') != 'TABLE':
            raise ConversionError(f'{origin}: only complete CREATE TABLE statements are accepted')
        shape = stmt.this
        if not isinstance(shape, exp.Schema) or not isinstance(shape.this, exp.Table):
            raise ConversionError(f'{origin}: CREATE TABLE LIKE/AS or missing column definitions')
        # Reject clauses we do not understand; do not accept CTAS mixed with columns.
        allowed_create = {'this', 'kind', 'exists', 'properties'}
        for key, value in stmt.args.items():
            if value and key not in allowed_create:
                raise ConversionError(f'{origin}: unsupported CREATE clause {key}')
        target = shape.this
        if target.catalog or (target.db and target.db != schema):
            raise ConversionError(f'{origin}: DDL database {target.db!r} does not match --schema {schema!r}')
        table_name = target.name
        table_fqn = fqn(service, database, schema, table_name)
        def warn(message):
            warnings.append({'source': origin, 'table': table_fqn, 'message': message})
        request = {'name': table_name, 'databaseSchema': fqn(service, database, schema),
                   'tableType': 'Regular', 'columns': [], 'tableConstraints': [],
                   'schemaDefinition': sql if len(statements) == 1 else stmt.sql(dialect='mysql') + ';'}
        constraints = request['tableConstraints']
        for entry in shape.expressions:
            if isinstance(entry, exp.ColumnDef):
                col, inline = column_request(entry, len(request['columns']) + 1, warn)
                request['columns'].append(col)
                constraints.extend(inline)
                continue
            entries = entry.expressions if isinstance(entry, exp.Constraint) else [entry]
            for item in entries:
                if isinstance(item, exp.PrimaryKey):
                    constraints.append({'constraintType': 'PRIMARY_KEY',
                                        'columns': plain_columns(item.expressions)})
                elif isinstance(item, exp.UniqueColumnConstraint):
                    if not isinstance(item.this, exp.Schema):
                        raise ConversionError('Unrecognized UNIQUE constraint')
                    constraints.append({'constraintType': 'UNIQUE',
                                        'columns': plain_columns(item.this.expressions)})
                elif isinstance(item, exp.ForeignKey):
                    ref = item.args.get('reference')
                    ref_schema = ref.this if ref is not None else None
                    if not isinstance(ref_schema, exp.Schema) or not isinstance(ref_schema.this, exp.Table):
                        raise ConversionError('Unrecognized FOREIGN KEY reference')
                    ref_table = ref_schema.this
                    if ref_table.catalog:
                        raise ConversionError('Cross-catalog foreign key is unsupported')
                    local = plain_columns(item.expressions)
                    remote = plain_columns(ref_schema.expressions)
                    if len(local) != len(remote):
                        raise ConversionError('FOREIGN KEY column count mismatch')
                    constraints.append({'constraintType': 'FOREIGN_KEY', 'columns': local,
                                        'referredColumns': [fqn(service, database, ref_table.db or schema,
                                                                ref_table.name, c) for c in remote]})
                    if ref.args.get('options'):
                        warn('FOREIGN KEY actions retained in schemaDefinition only')
                elif isinstance(item, exp.IndexColumnConstraint):
                    warn('Non-unique index retained in schemaDefinition only')
                elif isinstance(item, exp.CheckColumnConstraint):
                    warn('CHECK retained in schemaDefinition only')
                else:
                    raise ConversionError(f'{origin}: unsupported table element {type(item).__name__}')
        names = [c['name'] for c in request['columns']]
        if not names or len({n.casefold() for n in names}) != len(names):
            raise ConversionError(f'{origin}: empty table or duplicate column names')
        primary_keys = [c for c in constraints if c['constraintType'] == 'PRIMARY_KEY']
        if len(primary_keys) > 1:
            raise ConversionError(f'{origin}: multiple primary keys')
        for constraint in constraints:
            if any(n not in names for n in constraint['columns']):
                raise ConversionError(f'{origin}: constraint references unknown column')
        if primary_keys:
            pk_cols = primary_keys[0]['columns']
            for c in request['columns']:
                if c['name'] in pk_cols:
                    # OM rejects simultaneous column PRIMARY_KEY and table PRIMARY_KEY.
                    c['constraint'] = 'NOT_NULL'
        props = stmt.args.get('properties')
        for prop in props.expressions if props else []:
            if isinstance(prop, exp.SchemaCommentProperty):
                if not isinstance(prop.this, exp.Literal) or not prop.this.is_string:
                    raise ConversionError('Non-literal table comment')
                request['description'] = prop.this.this
            elif type(prop).__name__ in {'EngineProperty', 'CharacterSetProperty',
                                         'CollateProperty', 'AutoIncrementProperty',
                                         'RowFormatProperty'}:
                warn(f'{type(prop).__name__} retained in schemaDefinition only')
            else:
                raise ConversionError(f'{origin}: unsupported table property {type(prop).__name__}')
        from comment_annotations import apply_to_request
        tables.append(apply_to_request(request,security_classification))
    return tables, warnings


def convert_files(paths: list[Path], **kwargs) -> dict:
    tables, warnings, sources, seen = [], [], [], set()
    for path in paths:
        raw = path.read_bytes()
        converted, report = convert_sql(raw.decode('utf-8-sig'), origin=str(path), **kwargs)
        for request in converted:
            identity = request['databaseSchema'] + '.' + fqn(request['name'])
            if identity in seen:
                raise ConversionError(f'Duplicate table across input files: {identity}')
            seen.add(identity)
        tables.extend(converted)
        warnings.extend(report)
        sources.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    return {'formatVersion': 1, 'parser': 'sqlglot/' + sqlglot.__version__,
            'scope': {'service': kwargs['service'], 'database': kwargs['database'],
                      'schema': kwargs['schema'],
                      'fqn': fqn(kwargs['service'], kwargs['database'], kwargs['schema'])},
            'sources': sources, 'tables': tables, 'warnings': warnings}


def validate_sdk(tables: list[dict]) -> None:
    """Optional: install openmetadata-ingestion at the deployed server version."""
    from metadata.generated.schema.api.data.createTable import CreateTableRequest
    for table in tables:
        CreateTableRequest(**table)


def submit_tables(bundle: dict, url: str, token: str, *, allow_http=False) -> list[dict]:
    """Explicit upserts only; never infer table deletion from missing files."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from urllib.parse import quote
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise ConversionError('Invalid OM URL; use an origin with optional /api path')
    if parsed.scheme != 'https' and not allow_http:
        raise ConversionError('Use HTTPS or explicitly set --allow-http for local development')
    if not token:
        raise ConversionError('OM_TOKEN is required')
    if bundle.get('formatVersion') != 1 or not isinstance(bundle.get('tables'), list) or not bundle['tables']:
        raise ConversionError('Invalid or empty conversion bundle')
    base = url.rstrip('/')
    if not base.endswith('/api'):
        base += '/api'
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=frozenset({'GET', 'PUT'}), respect_retry_after_header=False)
    results = []
    with requests.Session() as session:
        session.mount('https://', HTTPAdapter(max_retries=retry))
        session.mount('http://', HTTPAdapter(max_retries=retry))
        session.headers.update({'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        # Preflight every parent before performing any writes.
        for parent in sorted({t['databaseSchema'] for t in bundle['tables']}):
            response = session.get(base + '/v1/databaseSchemas/name/' + quote(parent, safe=''),
                                   timeout=(10, 60), allow_redirects=False)
            if response.status_code != 200:
                raise ConversionError(f'Parent schema lookup HTTP {response.status_code}: {parent}; '
                                      'create OM service/database/schema first')
        for table in bundle['tables']:
            response = session.put(base + '/v1/tables', json=table,
                                   timeout=(10, 60), allow_redirects=False)
            if response.status_code not in {200, 201}:
                # Never print request headers/token or server bodies containing sensitive details.
                raise ConversionError(f'Upsert failed HTTP {response.status_code}: {table["name"]}; '
                                      f'{len(results)} preceding table(s) succeeded; rerun after fixing')
            results.append({'name': table['name'], 'status': response.status_code})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    convert = commands.add_parser('convert', help='Offline conversion; no network or database')
    convert.add_argument('files', nargs='+', type=Path)
    for name in ('service', 'database', 'schema'):
        convert.add_argument('--' + name, required=True)
    convert.add_argument('--output', required=True, type=Path)
    convert.add_argument('--strict', action='store_true', help='Fail on any metadata preserved only in raw DDL')
    convert.add_argument('--validate-sdk', action='store_true')
    convert.add_argument('--allow-empty', action='store_true', help='Allow an explicitly empty full snapshot')
    convert.add_argument('--security-classification', default='Security')
    submit = commands.add_parser('submit', help='Upsert an already generated bundle')
    submit.add_argument('bundle', type=Path)
    submit.add_argument('--url', default=os.getenv('OM_URL'))
    submit.add_argument('--allow-http', action='store_true')
    submit.add_argument('--validate-sdk', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'convert':
            bundle = convert_files(args.files, service=args.service, database=args.database,
                                   schema=args.schema, allow_empty=args.allow_empty,
                                   security_classification=args.security_classification)
            for warning in bundle['warnings']:
                print('WARNING: ' + warning['table'] + ': ' + warning['message'], file=sys.stderr)
            if args.strict and bundle['warnings']:
                raise ConversionError('Strict mode: unmapped metadata; no output written')
            if args.validate_sdk:
                validate_sdk(bundle['tables'])
            # All files are converted before output is written.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.output.with_name(args.output.name + '.tmp')
            tmp.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            tmp.replace(args.output)
            print(f'{len(bundle["tables"])} table(s) -> {args.output}')
        else:
            if not args.url:
                raise ConversionError('--url or OM_URL is required')
            bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
            if args.validate_sdk:
                validate_sdk(bundle['tables'])
            for result in submit_tables(bundle, args.url, os.getenv('OM_TOKEN', ''), allow_http=args.allow_http):
                print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # Do not catch KeyboardInterrupt/SystemExit. CI receives a nonzero exit code.
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
