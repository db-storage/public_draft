# Lifecycle synchronization for complete `schemas.sql`

This tool processes a **complete target snapshot** for one MySQL database. `schemas.sql` contains the latest CREATE TABLE for every target table, not DROP/ALTER/RENAME commands. Deletions come from “existing OM tables minus target tables”; renames use an explicit JSON manifest.

## Usage

Install `requirements.txt` and set OM_URL and OM_TOKEN (use CI Secret/Context). Parent OM DatabaseService, Database, and DatabaseSchema objects must already exist.

```bash
# 1. Convert a complete snapshot to OM request models; works without network access.
python mysql_ddl_to_om.py convert examples/schemas.sql \
  --service mysql_prod --database default --schema shop \
  --output models.json

# 2. Read OM state and generate a difference plan; writes nothing to OM.
python snapshot_sync.py plan models.json \
  --exclusive-schema --output plan.json

# For an explicit rename, add to the plan command:
# --renames examples/renames.json

# 3. Execute the plan and save a phase-by-phase journal.
python snapshot_sync.py apply plan.json --journal apply-journal.json

# A plan containing a table rename requires explicit acceptance of
# “new ID + soft deletion of old table” semantics:
# python snapshot_sync.py apply plan.json --journal apply-journal.json \
#   --acknowledge-rename-replacement
```

`--exclusive-schema` is an explicit ownership declaration: this tool exclusively manages every table in the specified OM DatabaseSchema, and active tables absent from the snapshot enter the soft-delete plan. **Do not use it for a Schema maintained jointly by mixed sources.** Run different databases separately with different scopes. Only OM metadata is deleted; the tool does not connect to business MySQL or run business DDL.

## Supported behavior

| Scenario | Handling |
|---|---|
| Multiple tables in one file | Parse all CREATE TABLE statements; write output only if all succeed |
| New table | Create with POST and retain the new ID; never blindly upsert over a concurrent creation |
| Add/change/delete columns | PATCH full columns and related constraints |
| Regular column updates | Preserve same-name description/displayName/tags; DDL comments take precedence |
| Table deletion | Soft-delete last with `hardDelete=false`; never hard-delete |
| Same-name soft-deleted table reappears | Restore its original ID, then update structure |
| Table rename | Explicit mapping, create/restore the new name, migrate selected annotations, validate, then soft-delete the old name |
| Column rename | Explicit mapping and migration of old description/displayName/tags; table ID remains unchanged |
| Foreign keys | Apply final foreign keys after all tables and columns are ready; supports cycles |
| Empty DB | Explicitly allow an empty snapshot and adjust deletion thresholds |
| Repeated synchronization | Re-plan/apply using current state; perform no writes when equal |
| Concurrent changes | Global baseline checks plus JSON Patch version/name tests |
| Mid-run failure | Stop immediately without further deletion, record a journal, and re-read state to plan again |

### Important: rename semantic boundary

Review of OM 1.12.0-release shows that `TableRepository` does not enable `EntityRepository.renameAllowed`, so PATCHing `name` is reverted. This tool cannot claim to rename the original table entity through PATCH. It explicitly uses a **replacement rename**, which requires `--acknowledge-rename-replacement`.

A table rename migrates table `description`, `displayName`, `tags`, `owners`, `domains`, and `extension`, plus column `description`, `displayName`, and `tags`. A comment in the DDL overrides a migrated comment.

**Not migrated or guaranteed continuous:** entity ID, history, lineage, test cases, Profile, usage statistics, column extensions, and related objects. To OM, a column rename can also be delete-old/add-new; this tool copies annotations but cannot guarantee continuity of column lineage or test references. The old table remains soft-deleted for auditing. If a soft-deleted entity already exists with the target name, it is restored and its target entity ID is used.

Preserving IDs and every associated object requires official rename support in your deployed OM and a dedicated integration; a client cannot emulate identical guarantees.

### Rename manifest

```json
{
  "tableRenames": [{"from": "orders", "to": "customer_orders"}],
  "columnRenames": [
    {"table": "customer_orders", "from": "status", "to": "order_status"}
  ]
}
```

For column renames, `table` uses the **final table name**. A normal column rename does not require also adding `tableRenames`. Without a manifest, no rename is inferred: absent old tables/columns are deleted and new ones are created, with no migration of prior annotations.

The manifest can remain for repeated runs: if the old name is inactive and the new name exists, the current structure is updated. It must not span a later business change that reuses the old name; each manifest should be tied to the current commit. Chained renames, name swaps, many-to-one mappings, target-column conflicts, and missing source/target ambiguity are rejected. Split such work into explicit snapshots.

## Plans, thresholds, and empty snapshots

`plan.json` records scope, parent IDs, source/bundle hashes, current entity baseline, target payloads, column differences, soft-delete manifests, and known limitations. `planHash` detects accidental edits; **it is not a signature or authorization mechanism**. Do not manually edit a plan before applying it.

- By default, regular table deletion is limited to 10 tables and 50% of previously active tables. An explicitly renamed old table does not count toward the regular deletion threshold, but rename acknowledgement is still required.
- To delete the final table, `schemas.sql` may be empty or comment-only, but configure it explicitly:

```bash
python mysql_ddl_to_om.py convert schemas.sql \
  --service mysql_prod --database default --schema shop \
  --allow-empty --output models.json
python snapshot_sync.py plan models.json --exclusive-schema \
  --allow-empty --max-delete-ratio 1 --max-deletes 10 --output plan.json
```

These are explicit CLI parameters and require no interactive confirmation. They are suitable for CI; higher thresholds allow a broader planned deletion range. Parse failures never become an empty snapshot.

## Foreign keys and execution phases

The order is:
1. Create or restore every target name, initially without FOREIGN_KEY.
2. Update all local columns, primary keys, and unique constraints; temporarily remove old foreign keys if needed.
3. Write all final foreign keys, including cycles.
4. GET again to validate the target structure.
5. Soft-delete old tables/old names last.

Foreign-key targets in the same scope must be in the final snapshot with matching columns, or planning fails. Cross-Schema foreign keys are checked for active target tables/columns before apply writes begin, but external schemas are not managed. Constraint-column ordering follows OM's set expression; do not use this catalog model as MySQL execution-semantics validation.

## Failures, reruns, and concurrency

This is a multi-API flow, **not a cross-table transaction, and it has no automatic rollback**. Tables already created/updated remain after a later failure; old tables are not soft-deleted until validation succeeds. The deletion phase can itself partially succeed.

Reads can retry. POST/PATCH/DELETE/restore are not retried automatically, avoiding repeated modification when a timeout leaves outcome unknown. After failure:
1. Inspect `apply-journal.json` (it marks `failed_replan_required`).
2. Run plan again for the same target snapshot, reading actual OM state.
3. Apply the new plan; do not continue the old one.

After an interrupted table rename, old and new names can both be active. The default plan rejects this conflict. Once confirmed as the target left by the preceding partial execution, add `--resume-renames` to **plan** with the original manifest, then still acknowledge rename semantics on apply. This parameter cannot arbitrarily overwrite a different existing business table.

Serialize jobs for one DB in CI; external connectors must not update the same structure concurrently. A complete baseline is compared before execution and PATCH uses version/name tests for additional conflict detection, but race windows remain between initial checks, POST, and soft deletion (the DELETE API has no client atomic version condition). No lock or full CAS guarantee is provided. An old commit must not re-plan and overwrite after a newer commit is published; CI should validate the release target revision.

Parent lookup, list pagination (`include=all`), cross-scope checks, and duplicate-cursor checks are implemented. The bot needs permission to read parents/tables and create, update, restore, and soft-delete.

## Validation status and limits

Tests cover the real converter, a stateful OM test double, and mocked HTTP parameters; no real OM service runs. The deployment version was not provided, so design is based on OM 1.12 request models and server source. Before deployment, validate JSON Patch tests, full-column deletion behavior, restore, bot permissions, entity soft deletion, and annotation preservation on a test OM. If the server ignores a write, read-back validation prevents subsequent old-table deletion. Comparison accounts for server lowercasing `dataTypeDisplay`; original enum casing remains in `schemaDefinition`. Primary keys are represented only in `tableConstraints`, not duplicated as column PRIMARY_KEY.

MySQL parsing capabilities follow the scope in README.md. Not all MySQL syntax is supported, and no MySQL-server semantic validation is performed. Lifecycle features do not remove those parsing boundaries.
