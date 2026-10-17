# Git source of truth: PR diffs and full initialization

This is the recommended entry point: `pr_diff_to_om.py`. It shares DDL conversion with `mysql_ddl_to_om.py` and security-tag parsing with `comment_annotations.py`. **Generation does not connect to MySQL, read OM, write OM, or require OM_URL/OM_TOKEN.**

## Modes

| Mode | Input | Output |
|---|---|---|
| diff | PR base/head commits | Requests only for added, changed, and removed tables |
| full | One head commit | Upsert requests for every existing configured table; no DELETE |

The implementation does not parse added SQL lines from a patch. It uses Git diff to find affected `schemas.sql` files, reads complete files from both commits, parses each, and compares tables by name. Git history is the sole comparison source; OM state is not consulted.

## Configuration

Create `om-mapping.json`; see `examples/git-sync/om-mapping.json`:

```json
{
  "databases": [
    {"path":"mysql/shop/schemas.sql","service":"mysql_prod","database":"default","schema":"shop"},
    {"path":"mysql/payment/schemas.sql","service":"mysql_prod","database":"default","schema":"payment"}
  ]
}
```

Paths are relative to the Git repository root. `database` is the OM Database container and `schema` is the MySQL database. Parent OM Service/Database/Schema objects must already exist; this tool does not generate parent connection configuration.

The mapping must cover relevant `schemas.sql` files. Diff mode fails for a changed unconfigured file, and full mode fails for any unconfigured `schemas.sql` in the repository, preventing missed databases. Full mode requires at least one real file for every configured scope; an empty DB may retain an empty or comment-only file. Maintain mappings for historical paths that no longer exist instead of assuming they were read successfully.

The mapping is a trusted input for each run and its hash is recorded. The tool does not compare historical mapping versions automatically. Service/Database/Schema mapping changes are catalog migrations, not ordinary table-structure changes, and need a separate plan.

## PR diffs

```bash
pip install -r requirements.txt
python pr_diff_to_om.py --mode diff \
  --repo /path/to/ddl-repo \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" \
  --config om-mapping.json --output om-artifact
```

By default, comparison is `merge-base(base, head) → head`, matching a PR's three-dot-diff semantics and avoiding misclassifying tables unique to the target branch as PR deletions.

For post-merge publication when the actual before/after commits are known:

```bash
python pr_diff_to_om.py --mode diff \
  --repo /path/to/ddl-repo \
  --base "$BEFORE_SHA" --head "$AFTER_SHA" --comparison direct \
  --config om-mapping.json --output om-artifact
```

The local Git repository needs both commits and their common ancestor, so CI must fetch sufficient history. The tool does not fetch or call the GitHub API, making it suitable for GitHub Enterprise and CircleCI. It reads committed blobs and ignores uncommitted workspace changes; SQL symlinks, directories, and submodules are rejected. `output` must be a new directory to prevent stale artifacts.

## Full initialization

```bash
python pr_diff_to_om.py --mode full \
  --repo /path/to/ddl-repo --head "$COMMIT_SHA" \
  --config om-mapping.json --output om-init-artifact
```

No base is needed. Even with no repository changes, this emits every CREATE TABLE for all configured databases. “All existing tables” means **all configured tables in Git**, not a scan of OM or production. Extra OM tables are not deleted. Same-name tables are updated by PUT; OM assets with different names are untouched.

## Output and OM API

| File | Contents | Direct OM request body? |
|---|---|---|
| `om-requests.json` | Commit, change summary, warnings, and ordered request manifest | No; CI consumes `requests` |
| `upserts.json` | Final CreateTableRequest array for all added/changed/full tables | Standard table-request array for OM bulk APIs; excludes deletes and does not replace full execution order |
| `000-put.json`, etc. | Standard JSON request body for each step | Yes, with manifest method/path/query |
| `summary.md` | Create, update, delete, and rename report | No; for PR/artifact review |

Request example:

```json
{
  "method":"DELETE",
  "path":"/api/v1/tables/name/mysql_prod.default.shop.old_table",
  "query":{"hardDelete":"false","recursive":"true"},
  "contentType":"application/json",
  "tableFqn":"mysql_prod.default.shop.old_table"
}
```

Generated order:
1. PUT `/api/v1/tables` with complete fields for changed/full tables, initially without FOREIGN_KEY.
2. PATCH `/api/v1/tables/name/{fqn}` with the full Git snapshot: columns, final constraints, DDL, descriptions, and tags. New tables now exist, allowing cyclic foreign keys.
3. DELETE `/api/v1/tables/name/{fqn}` to soft-delete tables absent from Git.

PATCH bodies are standard JSON Patch arrays with `application/json-patch+json`. PATCH also bypasses the Bot PUT policy that may retain old descriptions, allowing Git-comment changes/deletions to be explicit. Git is authoritative: **final table descriptions/tags and column descriptions/tags are replaced from Git; manual annotations absent from Git are not preserved.** To preserve such OM information, define field ownership separately; it cannot be claimed when OM is not read.

The manifest contains no GET or OM-state-derived UUID, version, or patch index. API execution belongs to a later CI job. For example, a trusted release job can consume requests in order:

```python
# Demonstrates standard request consumption only; this package does not run it automatically.
import json, os, requests
manifest = json.load(open("om-artifact/om-requests.json"))
for op in manifest["requests"]:
    response = requests.request(
        op["method"], os.environ["OM_ORIGIN"].rstrip("/") + op["path"],
        params=op.get("query"), json=op.get("body"),
        headers={"Authorization": "Bearer " + os.environ["OM_TOKEN"],
                 "Content-Type": op["contentType"]},
        timeout=(10, 60), allow_redirects=False,
    )
    response.raise_for_status()  # Stop on failure; do not continue to deletion.
```

`OM_ORIGIN` is the origin, such as `https://om.example.com`, without `/api`. This example is not a transaction, lock, recovery mechanism, or complete publisher. Authentication, version compatibility, permissions, soft-delete replay, and rebuilding a same-name soft-deleted table require testing on the deployed OM. A later operation can fail after an earlier success and cannot be rolled back automatically. Replaying an old deletion manifest can affect a subsequently rebuilt table, so CI must guarantee target versions and strict publish order.

## Drops and renames

- If a new Git version lacks an old table, emit DELETE for the old FQN; do not scan OM or delete tables outside Git history.
- On file deletion, read all tables from that file in the old commit and generate deletes.
- If a file path moves and old/new paths map to the same scope, compare complete before/after snapshots; it is not a table rename. The migration PR mapping must include aliases for both paths, and a table cannot be defined twice at once.
- A table-name change defaults to create + drop. Structural similarity is never used to guess a rename.
- `--renames examples/git-sync/pr-renames.json` explicitly labels a create/drop pair as a rename. Requests still upsert the new name and delete the old one; **the old OM entity ID, history, lineage, tests, and manual annotations are not retained or migrated.** This differs from the annotation-migration mode in the old `snapshot_sync.py`.
- Column renames are represented as a complete columns deletion/addition; no guess or OM column-annotation migration occurs.

## COMMENT and security classifications

Both table and column COMMENT are supported. Each machine annotation occupies its own line; remaining text becomes the description:

```sql
email VARCHAR(128) COMMENT 'User email address
@om.security=L3
@om.tag=PII.Email'
```

It maps to:

```json
{
  "description":"User email address",
  "tags":[
    {"tagFQN":"PII.Email","source":"Classification","labelType":"Manual","state":"Confirmed"},
    {"tagFQN":"Security.L3","source":"Classification","labelType":"Manual","state":"Confirmed"}
  ]
}
```

- `@om.security=L3` uses the default `Security` classification; `--security-classification DataSecurity` uses `DataSecurity.L3`.
- `@om.tag=PII.Email` supplies an exact tag FQN. Repeat it on multiple lines for multiple tags; duplicates are removed.
- These classifications/tags must exist in OM first. The generator does not query/create a security taxonomy or infer what L3 means; company governance defines that.
- The original COMMENT stays in `schemaDefinition`; machine-annotation lines are removed from `description`.
- Conflicting security levels on one column and unknown/malformed `@om` directives fail.
- Changing only a level/tag is detected by diff; removing an annotation emits empty `tags`, clearing it with Git as authority.
- A normal SQL line comment such as `-- @om.security=L3` is not a column annotation. This release parses only COMMENT literals explicitly bound to a table/column; arbitrary JSON comments or custom company annotation formats are never guessed.

## CI entry point

`schema-ci.sh` can be invoked by GitHub Actions or CircleCI:

```bash
# PR job
export SCHEMA_MODE=diff
export SCHEMA_REPO=/path/to/ddl-repo
export SCHEMA_BASE_SHA=...
export SCHEMA_HEAD_SHA=...
export SCHEMA_MAPPING=/path/to/om-mapping.json
export SCHEMA_OUTPUT_DIR=om-artifact
bash schema-ci.sh

# Initialization job
export SCHEMA_MODE=full
export SCHEMA_HEAD_SHA=...
export SCHEMA_OUTPUT_DIR=om-init-artifact
bash schema-ci.sh
```

For GitHub `pull_request`, use `event.pull_request.base.sha` / `head.sha`; for push publication, use `event.before` / `event.after` with `SCHEMA_COMPARISON=direct`. Do not treat `HEAD^` for a multi-commit push as the pre-release version. An all-zero `before` (first branch creation) cannot use diff; choose full or specify a real synchronized baseline. CircleCI callers must provide base/head and cannot infer the pre-release state from `CIRCLE_SHA1` alone.

PR jobs only generate/upload artifacts and need no OM secret. After merge, a trusted release job generates requests from the actual merged result. Serialize publication per database and verify the target commit. Because OM is not read, drift, missing historical changes, and concurrent modifications cannot be detected; this is an explicit Git-diff tradeoff. Perform an initial full initialization, then run diffs in order. After a missed publication, apply the missing changes or run full again (which still does not clean up extra OM assets).

## Examples and validation

`examples/git-sync/before.sql` and `after.sql` show a table addition, change, deletion, and security-level transition L2→L3. `diff-output` and `full-output` contain standard request bodies and manifests generated by the tool.

Tests create real commits in temporary local Git repositories. They cover merge-base/direct comparison, path moves, file changes, empty files, full initialization, multiple databases, unmapped paths, dirty workspaces, symlinks, comments, security tags, cyclic foreign keys, and request order, without accessing a real OM. SQL-dialect support follows the base converter documentation.
