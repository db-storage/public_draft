# Cassandra JSON Updater

Small fixed-schema CLI for six `tata` tables. Supports JSON `upsert` / `delete`, primary-key lookup, field-level diff, interactive approval, dry-run, single-row CAS and two-table membership synchronization.

## Requirements
- Go >= 1.25 (Apache Cassandra gocql v2.1.2)
- Cassandra 4.1/5.x recommended. Network access to native protocol port.
- Existing `tata` keyspace and six tables. `schema.cql` is a reference; **edit datacenter replication first** if provisioning.

## Build
```sh
go mod tidy
go build -o cassandra-sync .
```

## Run
```sh
export CASSANDRA_HOSTS='127.0.0.1'
export CASSANDRA_USER='myuser'          # optional
export CASSANDRA_PASSWORD='secret'     # optional; do not put secrets in commands
./cassandra-sync -f example.json --dry-run
./cassandra-sync -f example.json
./cassandra-sync -f example.json --non-interactive
./cassandra-sync -f example.json --yes --non-interactive
```

`--yes` approves updates and deletes, **not just inserts**. `--dry-run` wins over `--yes`. Operations run in JSON order; a failure stops subsequent operations (previous operations are NOT rolled back).

## Input
```json
{"operations":[
  {"table":"users","action":"upsert","data":{"user_id":"alice","user_type":"Human","cmdb":"x"}},
  {"table":"user_permissions","action":"delete","key":{"user_id":"alice","user_type":"Human","namespace":"dev"}}
]}
```
Only known table and column names are accepted. All PK fields are required and cannot be null/empty. `user_type` must be `Human` or `SDK`, `role_name` one of `read/write/worker/admin`. Timestamp columns take RFC3339 strings. Unspecified fields are preserved on existing rows. Explicit JSON null clears a non-PK field. Missing PK insert writes supplied fields only. There are no auto-generated timestamps. `groups.create_at` is intentionally the original column name; `group_members.added_at` is `text` in the provided DDL.

## Duplicate-PK behavior
- Missing PK -> insert (`IF NOT EXISTS` on single table)
- Existing PK with identical supplied values -> skip
- Existing PK with changed values -> old/new diff; prompt `[y/N]`, unless `--dry-run` or `--yes`
- In `--non-interactive` mode without `--yes`, a required confirmation exits nonzero
- Single-table UPDATE and DELETE use conditional LWT to detect changes to compared non-PK fields between read and write; membership mirroring does not have this protection

## Membership mirroring
Either `group_members` or `user_groups` is a logical membership operation; the tool always checks both tables and writes both via a two-statement LOGGED BATCH. `added_at` belongs only to `group_members`. If both rows exist and unchanged, skip; if only one exists, offer repair. DELETE removes both records after confirmation. Do not submit both sides of the same membership in the same JSON input.

**Important consistency limitation:** Logged Batch guarantees atomic application of the writes (eventual complete application), but not multi-partition read isolation. Cassandra cannot provide a normal cross-partition compare-and-swap transaction for these two differently partitioned tables. The two-table check and batch can race with other writers. To enforce strict concurrent write protection, serialize membership mutations through one writer or redesign around a common partition/consistency model.

## Operational notes
- `--dry-run` makes SELECT requests and requires Cassandra connectivity.
- Use a narrowly privileged Cassandra account, TLS/mTLS via gocql cluster config for production (not implemented by this example).
- This CLI does not automatically cascade deleting a group/user into other tables.
- `SELECT` uses `LOCAL_QUORUM`, and LWT uses driver defaults for serial consistency; ensure production settings match your topology.
- For a production deployment, add structured audit logging and an integration test against your Cassandra version.
