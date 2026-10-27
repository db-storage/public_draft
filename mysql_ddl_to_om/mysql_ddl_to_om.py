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


# OM 1.13.3 table.json enum. Unsigned is retained in dataTypeDisplay.
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


def fqn_parts(value: str) -> list[str]:
    """Split an OM FQN while retaining quoted segments as one part."""
    if not isinstance(value, str) or not value:
        raise ConversionError('Expected a non-empty OM FQN')
    parts, current, quoted = [], [], False
    for character in value:
        if character == '"':
            quoted = not quoted
        elif character == '.' and not quoted:
            if not current:
                raise ConversionError(f'Invalid OM FQN: {value!r}')
            parts.append(''.join(current))
            current = []
        else:
            current.append(character)
    if quoted or not current:
        raise ConversionError(f'Invalid OM FQN: {value!r}')
    parts.append(''.join(current))
    return parts


def mysql_identifier(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ConversionError(f'Invalid MySQL identifier: {value!r}')
    return '`' + value.replace('`', '``') + '`'


def mysql_string(value: str) -> str:
    if not isinstance(value, str) or '\x00' in value:
        raise ConversionError('MySQL COMMENT must be a string without NUL')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def rendered_type(column: dict) -> str:
    """Return a parser-validated MySQL type for a flat OM column."""
    data_type = column.get('dataType')
    display = column.get('dataTypeDisplay')
    if not isinstance(data_type, str) or data_type not in set(TYPE_MAP.values()):
        raise ConversionError(f'Unsupported OM column dataType: {data_type!r}')
    if display is None:
        display = data_type
        if data_type in {'CHAR', 'VARCHAR', 'BINARY', 'VARBINARY'}:
            length = column.get('dataLength')
            if not isinstance(length, int) or length <= 0:
                raise ConversionError(f'OM {data_type} column requires positive dataLength')
            display += f'({length})'
        elif data_type in {'DECIMAL', 'FLOAT', 'DOUBLE'} and column.get('precision') is not None:
            precision = column['precision']
            scale = column.get('scale')
            if not isinstance(precision, int) or precision <= 0:
                raise ConversionError(f'OM {data_type} column has invalid precision')
            display += f'({precision}' + (f', {scale}' if scale is not None else '') + ')'
    if not isinstance(display, str) or not display.strip():
        raise ConversionError('OM column dataTypeDisplay must be a non-empty string')
    try:
        statements = sqlglot.parse(f'CREATE TABLE probe (value {display})', read='mysql',
                                   error_level=ErrorLevel.RAISE)
    except ParseError as exc:
        raise ConversionError(f'Invalid OM dataTypeDisplay {display!r}') from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Create):
        raise ConversionError(f'Invalid OM dataTypeDisplay {display!r}')
    entries = statements[0].this.expressions if isinstance(statements[0].this, exp.Schema) else []
    if len(entries) != 1 or not isinstance(entries[0], exp.ColumnDef):
        raise ConversionError(f'Invalid OM dataTypeDisplay {display!r}')
    dtype = entries[0].args.get('kind')
    if entries[0].args.get('constraints') or not isinstance(dtype, exp.DataType):
        raise ConversionError(f'OM dataTypeDisplay must contain only a type: {display!r}')
    kind = dtype.this.name
    if kind not in TYPE_MAP or TYPE_MAP[kind] != data_type:
        raise ConversionError(f'OM dataTypeDisplay {display!r} does not match {data_type!r}')
    return dtype.sql(dialect='mysql')


def render_om_table(table: dict) -> tuple[str, list[str]]:
    """Render the core, structurally round-trippable portion of one OM table."""
    if not isinstance(table, dict):
        raise ConversionError('OM table request must be an object')
    if table.get('tableType', 'Regular') != 'Regular':
        raise ConversionError('Only OM Regular tables can be rendered as CREATE TABLE')
    name, columns = table.get('name'), table.get('columns')
    if not isinstance(name, str) or not isinstance(columns, list) or not columns:
        raise ConversionError('OM table requires name and non-empty columns')
    if any(not isinstance(column, dict) for column in columns):
        raise ConversionError('OM column must be an object')
    warnings = []
    sorted_columns = sorted(enumerate(columns), key=lambda pair: (pair[1].get('ordinalPosition', pair[0] + 1), pair[0]))
    definitions = []
    for _, column in sorted_columns:
        definition = mysql_identifier(column.get('name')) + ' ' + rendered_type(column)
        constraint = column.get('constraint', 'NULL')
        if constraint == 'NOT_NULL' or constraint == 'PRIMARY_KEY':
            definition += ' NOT NULL'
        elif constraint not in {None, 'NULL'}:
            warnings.append(f'{name}.{column.get("name")}: column constraint {constraint} omitted')
        if 'description' in column and column['description'] is not None:
            definition += ' COMMENT ' + mysql_string(column['description'])
        definitions.append(definition)
    for constraint in table.get('tableConstraints') or []:
        if not isinstance(constraint, dict) or not isinstance(constraint.get('columns'), list):
            raise ConversionError(f'{name}: invalid table constraint')
        columns_sql = ', '.join(mysql_identifier(value) for value in constraint['columns'])
        kind = constraint.get('constraintType')
        if kind == 'PRIMARY_KEY':
            definitions.append('PRIMARY KEY (' + columns_sql + ')')
        elif kind == 'UNIQUE':
            definitions.append('UNIQUE (' + columns_sql + ')')
        elif kind == 'FOREIGN_KEY':
            referred = constraint.get('referredColumns')
            if not isinstance(referred, list) or len(referred) != len(constraint['columns']) or not referred:
                raise ConversionError(f'{name}: invalid FOREIGN_KEY referredColumns')
            targets = [fqn_parts(value) for value in referred]
            if any(len(target) != 5 for target in targets) or len({tuple(target[:4]) for target in targets}) != 1:
                raise ConversionError(f'{name}: FOREIGN_KEY must refer to one table')
            target = targets[0]
            target_sql = '.'.join(mysql_identifier(value) for value in target[2:4])
            definitions.append('FOREIGN KEY (' + columns_sql + ') REFERENCES ' + target_sql + ' ('
                               + ', '.join(mysql_identifier(value[4]) for value in targets) + ')')
        else:
            warnings.append(f'{name}: table constraint {kind!r} omitted')
    statement = 'CREATE TABLE ' + mysql_identifier(name) + ' (\n  ' + ',\n  '.join(definitions) + '\n)'
    if 'description' in table and table['description'] is not None:
        statement += ' COMMENT=' + mysql_string(table['description'])
    return statement + ';', warnings


def core_projection(table: dict) -> dict:
    """Stable subset used to validate the reversible part of an OM request."""
    columns = []
    ordered_columns = sorted(enumerate(table['columns']),
                             key=lambda pair: (pair[1].get('ordinalPosition', pair[0] + 1), pair[0]))
    for position, (_, column) in enumerate(ordered_columns, start=1):
        columns.append({
            'name': column['name'], 'dataType': column['dataType'],
            'dataTypeDisplay': rendered_type(column),
            'dataLength': column.get('dataLength'), 'precision': column.get('precision'),
            'scale': column.get('scale'), 'constraint': column.get('constraint', 'NULL'),
            'description': column.get('description'), 'ordinalPosition': position,
        })
    constraints = []
    for constraint in table.get('tableConstraints') or []:
        if constraint.get('constraintType') in {'PRIMARY_KEY', 'UNIQUE', 'FOREIGN_KEY'}:
            constraints.append({key: constraint[key] for key in ('constraintType', 'columns', 'referredColumns')
                                if key in constraint})
    return {'name': table['name'], 'description': table.get('description'),
            'columns': columns, 'tableConstraints': constraints}


def om_tables(payload) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get('tables')
    if not isinstance(payload, list) or not payload:
        raise ConversionError('Expected a non-empty OM bundle or CreateTableRequest array')
    return payload


def reverse_om_tables(tables: list[dict], *, verify: bool = False) -> tuple[str, list[str]]:
    """Render OM requests and optionally verify their core structure through the forward converter."""
    statements, warnings = [], []
    for table in tables:
        statement, table_warnings = render_om_table(table)
        statements.append(statement)
        warnings.extend(table_warnings)
        if verify:
            parts = fqn_parts(table.get('databaseSchema'))
            if len(parts) != 3:
                raise ConversionError(f'{table.get("name")}: databaseSchema must be a three-part FQN')
            converted, _ = convert_sql(statement, service=parts[0], database=parts[1], schema=parts[2])
            if len(converted) != 1 or core_projection(table) != core_projection(converted[0]):
                raise ConversionError(f'{table.get("name")}: reverse validation changed core table structure')
    return '\n\n'.join(statements) + '\n', warnings


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
    reverse = commands.add_parser('reverse', help='Render core MySQL DDL from OM request JSON')
    reverse.add_argument('input', type=Path, help='Conversion bundle or CreateTableRequest array')
    reverse.add_argument('--output', required=True, type=Path)
    reverse.add_argument('--verify', action='store_true', help='Round-trip validate core table structure')
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
        elif args.command == 'submit':
            if not args.url:
                raise ConversionError('--url or OM_URL is required')
            bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
            if args.validate_sdk:
                validate_sdk(bundle['tables'])
            for result in submit_tables(bundle, args.url, os.getenv('OM_TOKEN', ''), allow_http=args.allow_http):
                print(json.dumps(result, ensure_ascii=False))
        else:
            tables = om_tables(json.loads(args.input.read_text(encoding='utf-8')))
            ddl, warnings = reverse_om_tables(tables, verify=args.verify)
            for warning in warnings:
                print('WARNING: ' + warning, file=sys.stderr)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.output.with_name(args.output.name + '.tmp')
            tmp.write_text(ddl, encoding='utf-8')
            tmp.replace(args.output)
            print(f'{len(tables)} table(s) -> {args.output}')
    except Exception as exc:
        # Do not catch KeyboardInterrupt/SystemExit. CI receives a nonzero exit code.
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
