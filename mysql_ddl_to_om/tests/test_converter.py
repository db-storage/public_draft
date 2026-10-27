import json
from importlib.metadata import version
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from mysql_ddl_to_om import (
    ConversionError, convert_sql, convert_files, main, reverse_om_tables,
    submit_tables, validate_sdk,
)


def convert(sql):
    return convert_sql(sql, service='mysql_prod', database='default', schema='shop')


def test_example_snapshot():
    requests, warnings = convert((Path(__file__).parents[1] / 'examples/orders.sql').read_text())
    t = requests[0]
    assert t['databaseSchema'] == 'mysql_prod.default.shop'
    assert t['description'] == 'Orders table'
    columns = {c['name']: c for c in t['columns']}
    assert columns['amount']['precision'] == 18
    assert columns['amount']['scale'] == 2
    assert columns['status']['dataLength'] == 32
    assert columns['status']['description'] == 'Order status'
    assert columns['delivery_time']['constraint'] == 'NULL'
    assert columns['created_at']['dataType'] == 'TIMESTAMP'
    assert columns['id']['dataTypeDisplay'] == 'BIGINT UNSIGNED'
    assert t['tableConstraints'][0] == {'constraintType': 'PRIMARY_KEY', 'columns': ['tenant_id', 'id']}
    assert columns['tenant_id']['constraint'] == 'NOT_NULL'
    assert 'CREATE TABLE' in t['schemaDefinition']
    assert len(warnings) == 6


@pytest.mark.parametrize('sqltype,expected', [
    ('TINYINT(1)', 'TINYINT'), ('SMALLINT UNSIGNED', 'SMALLINT'),
    ('MEDIUMINT', 'INT'), ('INT UNSIGNED', 'INT'), ('BIGINT', 'BIGINT'),
    ('CHAR(4)', 'CHAR'), ('VARCHAR(255)', 'VARCHAR'), ('VARBINARY(8)', 'VARBINARY'),
    ('DECIMAL(20,6)', 'DECIMAL'), ('FLOAT', 'FLOAT'), ('DOUBLE', 'DOUBLE'),
    ('DATE', 'DATE'), ('TIME(6)', 'TIME'), ('DATETIME(6)', 'DATETIME'),
    ('TIMESTAMP', 'TIMESTAMP'), ('JSON', 'JSON'), ('YEAR', 'YEAR'), ('BIT(8)', 'BIT'),
    ("ENUM('a,b','x')", 'ENUM'), ("SET('a','b')", 'SET'),
    ('TINYTEXT', 'TEXT'), ('LONGTEXT', 'TEXT'), ('MEDIUMBLOB', 'MEDIUMBLOB'),
    ('BOOL', 'BOOLEAN'),
])
def test_type_mapping(sqltype, expected):
    tables, _ = convert(f'CREATE TABLE t (c {sqltype})')
    assert tables[0]['columns'][0]['dataType'] == expected


def test_comments_delimiters_and_multiple_tables():
    tables, _ = convert("-- note\nCREATE TABLE t (x VARCHAR(12) COMMENT 'a,b;Chinese'); /* note */ CREATE TABLE u (id INT)")
    assert len(tables) == 2
    assert tables[0]['columns'][0]['description'] == 'a,b;Chinese'


def test_foreign_key():
    tables, warnings = convert('''CREATE TABLE child (
        id INT PRIMARY KEY, parent_id INT NOT NULL,
        CONSTRAINT fk FOREIGN KEY(parent_id) REFERENCES shop.parent(id) ON DELETE CASCADE
    )''')
    t = tables[0]
    fk = t['tableConstraints'][1]
    assert fk['referredColumns'] == ['mysql_prod.default.shop.parent.id']
    assert fk['columns'] == ['parent_id']
    assert t['columns'][0]['constraint'] == 'NOT_NULL'
    assert warnings


def test_unique_nullability():
    t = convert('CREATE TABLE t (a INT UNIQUE NOT NULL, b INT, UNIQUE(a,b))')[0][0]
    assert t['columns'][0]['constraint'] == 'NOT_NULL'
    assert t['columns'][1]['constraint'] == 'NULL'
    assert len(t['tableConstraints']) == 2


def test_generated_check_reported():
    t, warnings = convert('CREATE TABLE t (a INT, b INT GENERATED ALWAYS AS (a+1) STORED, CHECK(a>0))')
    assert len(t[0]['columns']) == 2
    assert len(warnings) == 2


@pytest.mark.parametrize('sql', [
    'ALTER TABLE t ADD x INT', 'DROP TABLE t', 'SELECT 1',
    'CREATE TABLE t AS SELECT 1', 'CREATE TABLE t LIKE old',
    'CREATE TABLE other.t (x INT)', 'CREATE TABLE t (x INT, X INT)',
    'CREATE TABLE t (x INT, PRIMARY KEY(y))',
    'CREATE TABLE t (x INT, UNIQUE (x(3)))',
    'CREATE TABLE t (x INT PRIMARY KEY, PRIMARY KEY(x))',
    'CREATE TABLE t (x INT); INSERT INTO t VALUES(1)',
    'CREATE TABLE t (x POINT)', 'CREATE TABLE t (x INT ZEROFILL)',
    '/*!50001 CREATE TABLE t (x INT) */;', '',
    'CREATE TEMPORARY TABLE t (id INT)',
])
def test_unsupported_fails(sql):
    with pytest.raises(ConversionError):
        convert(sql)


def test_duplicate_across_files(tmp_path):
    a, b = tmp_path/'a.sql', tmp_path/'b.sql'
    a.write_text('CREATE TABLE t (x INT)')
    b.write_text('CREATE TABLE t (y INT)')
    with pytest.raises(ConversionError, match='Duplicate'):
        convert_files([a,b], service='s', database='default', schema='shop')


def test_no_partial_output(tmp_path):
    source, output = tmp_path/'a.sql', tmp_path/'out.json'
    source.write_text('CREATE TABLE t (x INT); ALTER TABLE t ADD y INT')
    assert main(['convert', str(source), '--service','s','--database','default',
                 '--schema','shop','--output',str(output)]) == 1
    assert not output.exists()


def test_strict(tmp_path):
    source, output = tmp_path/'a.sql', tmp_path/'out.json'
    source.write_text('CREATE TABLE t (x INT DEFAULT 1)')
    assert main(['convert', str(source), '--service','s','--database','default',
                 '--schema','shop','--output',str(output),'--strict']) == 1
    assert not output.exists()


def test_quoted_fqn():
    t = convert('CREATE TABLE `order.detail` (`a.b` INT)')[0][0]
    assert t['name'] == 'order.detail'
    assert t['columns'][0]['name'] == 'a.b'


def bundle():
    return {'formatVersion': 1, 'tables': convert('CREATE TABLE t (id INT)')[0]}


def session_mock(get_status=200, put_status=200):
    s = Mock()
    s.__enter__ = Mock(return_value=s)
    s.__exit__ = Mock(return_value=False)
    s.get.return_value.status_code = get_status
    s.put.return_value.status_code = put_status
    return s


def test_rest_payload_and_auth():
    s = session_mock()
    with patch('requests.Session', return_value=s):
        result = submit_tables(bundle(), 'https://om.example/api', 'test-token')
    assert result == [{'name':'t','status':200}]
    assert s.put.call_args.args[0] == 'https://om.example/api/v1/tables'
    assert s.put.call_args.kwargs['json'] == bundle()['tables'][0]
    assert s.put.call_args.kwargs['allow_redirects'] is False
    s.headers.update.assert_called_once_with({'Authorization':'Bearer test-token','Content-Type':'application/json'})


def test_parent_failure_no_write():
    s = session_mock(get_status=404)
    with patch('requests.Session', return_value=s), pytest.raises(ConversionError, match='Parent'):
        submit_tables(bundle(), 'https://om.example', 'test-token')
    s.put.assert_not_called()


def test_api_failure_is_error():
    s = session_mock(put_status=403)
    with patch('requests.Session', return_value=s), pytest.raises(ConversionError, match='403'):
        submit_tables(bundle(), 'https://om.example', 'test-token')


def test_http_requires_opt_in():
    with pytest.raises(ConversionError, match='HTTPS'):
        submit_tables(bundle(), 'http://localhost:8585', 'test-token')


def test_om_1_13_3_sdk_models():
    pytest.importorskip('metadata.generated.schema.api.data.createTable')
    assert version('openmetadata-ingestion') == '1.13.3.0'
    tables = convert((Path(__file__).parents[1]/'examples/orders.sql').read_text())[0]
    tables += convert("CREATE TABLE parent(id INT PRIMARY KEY); CREATE TABLE child(id INT, FOREIGN KEY(id) REFERENCES parent(id))")[0]
    validate_sdk(tables)


def test_reverse_round_trip_preserves_core_table_fields():
    tables = convert((Path(__file__).parents[1] / 'examples/orders.sql').read_text())[0]
    ddl, warnings = reverse_om_tables(tables, verify=True)
    assert warnings == []
    assert 'CREATE TABLE `orders`' in ddl
    assert 'BIGINT UNSIGNED' in ddl
    assert 'PRIMARY KEY (`tenant_id`, `id`)' in ddl
    assert "COMMENT 'Order status'" in ddl


def test_reverse_round_trip_preserves_foreign_key_and_quoted_names():
    tables = convert('''CREATE TABLE `order.detail` (
        `id` BIGINT PRIMARY KEY,
        `customer.id` BIGINT NOT NULL,
        FOREIGN KEY (`customer.id`) REFERENCES shop.customers(id)
    ) COMMENT 'Orders' ''')[0]
    ddl, warnings = reverse_om_tables(tables, verify=True)
    assert warnings == []
    assert '`order.detail`' in ddl
    assert 'REFERENCES `shop`.`customers` (`id`)' in ddl


def test_reverse_cli_accepts_bundle_and_validates(tmp_path):
    source, bundle_path, output = tmp_path/'a.sql', tmp_path/'models.json', tmp_path/'roundtrip.sql'
    source.write_text('CREATE TABLE t(id INT PRIMARY KEY, name VARCHAR(8) COMMENT \'Name\')')
    assert main(['convert', str(source), '--service', 's', '--database', 'default',
                 '--schema', 'shop', '--output', str(bundle_path)]) == 0
    assert main(['reverse', str(bundle_path), '--output', str(output), '--verify']) == 0
    assert 'CREATE TABLE `t`' in output.read_text()


def test_full_snapshot_add_remove_and_modify():
    old = convert('CREATE TABLE t (id INT PRIMARY KEY, status VARCHAR(8), obsolete INT)')[0][0]
    new = convert('CREATE TABLE t (id INT PRIMARY KEY, status VARCHAR(32), delivery_time DATETIME)')[0][0]
    assert old['name'] == new['name']
    assert [c['name'] for c in new['columns']] == ['id', 'status', 'delivery_time']
    assert new['columns'][1]['dataLength'] == 32
    assert old['columns'][1]['dataLength'] == 8
