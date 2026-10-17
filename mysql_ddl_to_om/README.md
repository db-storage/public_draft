# MySQL DDL → OpenMetadata

**Recommended: use Git as the source of truth with the PR-diff/full-initialization workflow that does not read OpenMetadata, via `pr_diff_to_om.py`. See [GIT_SYNC.md](GIT_SYNC.md). COMMENT annotations support security levels and tags.**

**Optional legacy workflow (reads OpenMetadata): use `snapshot_sync.py` for complete multi-table snapshots, deletion, restoration, and table/column renames. See [SNAPSHOT_SYNC.md](SNAPSHOT_SYNC.md). The `submit` command on this page is the legacy create-or-update-only interface.**

The tool reads complete MySQL `CREATE TABLE` files from a Git checkout, parses them with SQLGlot, and generates OpenMetadata `CreateTableRequest` JSON. It does not require a MySQL connection or custom SQL lexer/parser. Conversion and submission are separate, so CI can review output before submitting it after merge.

## 1. Quick start

Requires Python 3.10+ (Python 3.12 was used for this project). From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python mysql_ddl_to_om.py convert examples/orders.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json
```

Pass multiple files as positional arguments, for example `schema/*.sql`. Each file may contain multiple complete `CREATE TABLE` statements, but all input must target one MySQL database. Run the command separately for different databases.

- `--service`: the OM DatabaseService name, for example `mysql_prod`.
- `--database`: the OM Database container, for example `default`. This is not the MySQL database name; match your existing OM catalog/connector naming.
- `--schema`: the target MySQL database name and the OM DatabaseSchema used by this tool, for example `shop`.
- In this example the parent FQN is `mysql_prod.default.shop`, and the table FQN is `mysql_prod.default.shop.orders`.
- Qualified SQL such as `shop.orders` must match `--schema`; unqualified tables use the supplied schema.
- Output is a bundle. Each object in `tables` is an API request body; do not PUT the entire bundle to OM.
- A table cannot appear more than once in an input batch. Conversion failures return nonzero and write no partial result. CI must check the exit code and not publish a stale output file.

## 2. Submit to OM

Create the corresponding Service, Database, and DatabaseSchema in OM first. The bot needs permission to read parents and create/update target tables. The tool only updates tables, does not create parents, and does not connect to the source database.

```bash
export OM_URL='https://om.example.com'  # https://om.example.com/api is also accepted
# Inject OM_TOKEN through CI secrets/context; do not put it in source or command lines.
python mysql_ddl_to_om.py submit models.json
```

Submission uses `PUT /api/v1/tables` and first verifies that every parent schema exists. Failures return nonzero. HTTP 429/500/502/503/504 and selected network failures retry up to three times. Writes run table by table, not as a cross-table transaction; earlier tables may already have been written if a later write fails. Re-run the same bundle after fixing the issue. Table-version and event behavior depend on your deployed server version.

Use `--allow-http` only for local HTTP debugging. TLS is verified by default, redirects are not followed, and bot tokens are never printed.

Before production use, test creates, column edits, and column deletions on a test OM environment. A full `columns` list has replacement/deletion semantics, so do not send only newly added columns. Verify how your version preserves manual descriptions, tags, and owners. The tool deliberately does not GET-merge or protect manual edits, avoiding concurrent writes from multiple structure-sync sources.

## 3. Conversion scope

| Information | Output |
|---|---|
| Table/column names and order | `name`, `ordinalPosition` |
| Integers, floating point, DECIMAL, CHAR/VARCHAR, binary, text, BLOB, time, JSON, YEAR, BIT, ENUM/SET | `dataType` + `dataTypeDisplay` |
| VARCHAR/CHAR/BINARY/VARBINARY length | `dataLength` |
| Explicit DECIMAL/FLOAT/DOUBLE precision and scale | `precision`, `scale` |
| Table and column comments | `description` |
| NULL / NOT NULL | `constraint` |
| Single/composite primary keys and unique constraints | `tableConstraints`; primary-key columns use NOT_NULL and do not duplicate PRIMARY_KEY |
| Foreign keys | Local columns + target referredColumns FQN |
| Original CREATE TABLE definition | `schemaDefinition` |

Details:
- UNSIGNED maps to the same-width OM integer enum and remains in `dataTypeDisplay`. MEDIUMINT maps to INT; LONGTEXT/TINYTEXT map to TEXT. OM types are catalog categories, not lossless MySQL execution types.
- CHAR/BINARY without a length use MySQL's default length of 1; VARCHAR/VARBINARY without a length fail.
- TINYINT(1) remains TINYINT; it is not assumed to be BOOLEAN. BOOL is normalized to BOOLEAN by the parser.
- TIMESTAMP maps to TIMESTAMP and DATETIME maps to DATETIME. Fractional precision, BIT width, integer display width, and ENUM/SET values remain in `dataTypeDisplay`, rather than being placed in incompatible `dataLength`/`precision` fields.
- All primary keys use table-level PRIMARY_KEY and their columns are marked NOT_NULL; OM rejects duplicate PRIMARY_KEY expressions at column and table level.
- For single-table files, `schemaDefinition` keeps the original text. For multi-table files, each table uses its SQLGlot-normalized statement. The source SHA-256 is stored in the bundle's `sources`.
- Defaults, auto-increment, ON UPDATE, generated formulas, CHECK constraints, regular indexes, engines, and character sets remain in `schemaDefinition` and are listed in warnings, rather than becoming independent structured fields.
- `--strict` fails for any such warning, including ENGINE/CHARSET. Use it when all metadata must be structured; otherwise review warnings during normal ingestion.
- Foreign keys default to the same service/database container and can reference other MySQL databases (schemas). Target tables are not created or ordered automatically, and relationship types are not inferred; targets must exist first or be uploaded in dependency order.

Unsupported types, expression/prefix unique indexes, and unknown constraints/table options fail rather than degrade to UNKNOWN. ALTER, DROP, CTAS, CREATE LIKE, temporary tables, executable MySQL comments (`/*! ... */`), unsupported spatial types such as POINT, and syntax that cannot be read reliably (such as ZEROFILL in tests) are explicitly rejected. This tool defines a syntax boundary and does not claim support for all MySQL DDL.

**SQLGlot is a parser, not a MySQL validator.** Producing an AST does not mean MySQL will accept the DDL. Without a temporary database, server-identical syntax/semantic validation is unavailable. SQL_MODE and version-specific behavior are not simulated. Add representative repository DDL samples as regression tests.

## 4. Optional deployed-SDK validation

JSON output follows the OM 1.12 official table model. Because the deployed OM version is unknown, validate against your deployed version. `--validate-sdk` validates every request with the installed SDK's `CreateTableRequest` before conversion or submission.

Install a server-compatible full `openmetadata-ingestion` environment separately, then run:

```bash
python mysql_ddl_to_om.py convert examples/orders.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json --validate-sdk
```

The SDK environment has many dependencies; check compatibility with the pinned SQLGlot version. Offline conversion needs only the two packages in `requirements.txt`; REST submission does not require ingestion.

If you already have an SDK client, reuse the conversion function directly:

```python
from pathlib import Path
from mysql_ddl_to_om import convert_files
from metadata.generated.schema.api.data.createTable import CreateTableRequest

bundle = convert_files(
    [Path('schema/orders.sql')],
    service='mysql_prod', database='default', schema='shop',
)
for payload in bundle['tables']:
    # client is an OpenMetadata SDK client configured with a bot token
    client.create_or_update(CreateTableRequest(**payload))
```

For a custom connector, `Source._iter` can generate `Either(right=CreateTableRequest(**payload))` and pass it to the standard metadata-rest Sink; parsing and mapping remain unchanged.

## 5. Tests

Lifecycle-sync tests cover snapshot comparison, annotation migration, recovery from interrupted renames, soft deletion, cyclic foreign keys, pagination, concurrent changes, and request-parameter checks. See [VALIDATION.md](VALIDATION.md) for full results.

```bash
pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Disabling third-party pytest auto-loading prevents plugins bundled with ingestion from affecting project tests. Official model-validation tests are skipped when the SDK is absent. No real OM service is connected; API permissions, version behavior, and foreign-key target validation must be verified in your environment.

## 6. CI recommendations

1. Check out the exact commit, convert complete CREATE TABLE files, and check nonzero exits and warnings.
2. Archive `models.json` with the source commit SHA; SHA-256 confirms provenance but not that DDL was executed.
3. After merge, publish an artifact matching the target commit. Serialize each target to prevent a stale run from overwriting a newer result.
4. Design explicit operations for file deletion and table renames. This tool never deletes tables merely because a file is absent.
5. Merge synchronization represents the repository's intended structure. If the catalog must represent executed production state, publish the artifact for the corresponding commit after the ticket succeeds.

## References

- SQLGlot: https://github.com/tobymao/sqlglot
- OM table model: https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/entity/data/table.json
- OM CreateTableRequest: https://github.com/open-metadata/OpenMetadata/blob/1.12.0-release/openmetadata-spec/src/main/resources/json/schema/api/data/createTable.json
- OM custom connectors: https://docs.open-metadata.org/latest/connectors/custom-connectors
