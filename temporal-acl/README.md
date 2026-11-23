# Temporal ACL Cassandra PermissionModel (v1, no cache)

## Scope

Uses six tables from `cassandra_tables.cql`; read path uses four of them:
1. `users`: reject unknown principals (return empty permissions).
2. `user_permissions`: direct namespace grants.
3. `user_groups`: per-user group memberships.
4. `group_permissions`: namespace grants inherited from each group.

`groups` stores group metadata; `group_members` is the reverse membership index used by group administration. Neither is needed for a by-user permissions lookup. **Writers must keep `user_groups` and `group_members` synchronized.** Cassandra does not provide automatic cross-partition atomic synchronization.

## Semantics

- `user_type` is case-sensitive and must be `Human` or `SDK` as provided in the source schema.
- Namespace roles are bit masks, matching Temporal's `RoleWorker`, `RoleReader`, `RoleWriter`, `RoleAdmin` values. A direct grant and inherited grants are merged with bitwise OR; `admin` is not automatically converted into other bits.
- ACL query errors and invalid stored role names fail closed (return an error). No cache, no automatic permit-on-error.
- The `users` table is an existence gate; missing user yields no permissions.
- `role_name=worker` alone may not grant task-polling rights with the default Temporal Authorizer: confirm your target Temporal release's authorization mapping.
- No system-level privileges are emitted by the integration adapter. Namespace grants do not by themselves permit global APIs such as `ListNamespaces`; consider a carefully scoped custom Authorizer for UI usage.
- No wildcard expansion. Namespace names must match exactly.
- This is **read-only**; writes to the ACL tables are managed externally.

## Setup

1. Review `schema.cql` and adjust the **actual Cassandra datacenter name and replication factor** before executing. The file illustrates the required primary keys; it is **not** a safe automated migration for existing tables. If the original tables already exist with different primary keys, migrate explicitly.
2. Edit `config.example.json` (avoid keeping actual passwords in git).
3. `go mod tidy`
4. `go test ./acl/...`
5. `go run ./cmd/acl-check config.example.json bob Human`

The module is designed to be embedded into a Temporal server process. Create one `PermissionModel` per **Frontend process** after config load; keep the resulting `gocql.Session` until shutdown and call `Close` when server stops. The driver manages per-host connection pools (`num_conns`); never create a session per request. Each call queries Cassandra, so monitor QPS/latency and add a cache decorator later if needed.

## Temporal integration

`temporaladapter/mapper.go` is guarded by `//go:build temporal` to avoid forcing a second Temporal Server dependency into the standalone ACL unit tests. To use it in a Temporal fork, copy it into that repo, update the ACL import path, and instantiate:

```go
model, err := acl.NewFromConfig(cfg)
if err != nil { return err }
// Wire into the Frontend process lifecycle; close model on shutdown.
mapper := &temporaladapter.Mapper{
    Model: model,
    Resolve: verifiedIdentityResolver, // implement with your Okta/SPIRE verifier
    Timeout: 500*time.Millisecond,
}
// Register the mapper with temporal.WithClaimMapper(...), or adapt
// GetClaimMapperFromConfig in the Temporal fork.
// Ensure Temporal's Authorizer is configured to "default" or a secure custom implementation.
```

Important: `IdentityResolver` must perform **actual authentication**; it is intentionally not supplied, since the user's Okta issuer/audience/JWKS and SPIFFE trust domain are not provided. Mapping an unverified token `sub` to a user is unsafe. The integration is therefore **complete for the ACL lookup**, but cannot be deployed as a functioning authentication plugin until this verifier is connected.

`ClaimMapper.GetClaims` does not accept `context.Context` in current Temporal versions. The adapter uses its own 500ms timeout, which is not automatically cancelled when the client disconnects.

## Scalability / limitations

- Each request reads `users`, `user_permissions`, `user_groups`, then one `group_permissions` partition per group. For a user with G groups this is G+3 queries. Add a per-user cache only if measured performance needs it.
- `max_groups` bounds accidental fan-out. There is no hard row-count bound in this initial implementation; apply database-side quotas or add explicit limits if administrators can create arbitrarily large partitions.
- The query is read-only and uses LOCAL_QUORUM; use an appropriate compatible write consistency and coordinate multi-table updates with the writer.
- Group membership and group-permission rows are not snapshotted atomically. Authorization during concurrent policy writes can briefly observe mixed versions; if this is unacceptable, implement versioned snapshots or an explicit consistency protocol.
- TLS, connection authentication, cross-DC locality, metrics and retry policy must be integrated with your production deployment requirements. Currently password authentication is optional and Cassandra transport TLS is **not yet configured**. Do not deploy plaintext traffic across untrusted networks.
- Config option `enabled=false` raises an error in the factory: it must never disable authorization silently. A caller can instead explicitly choose a separately secured provider.

## Development test commands

`go test ./acl/...` validates direct + inherited grant merging, missing user, unknown role, group cap and Cassandra error behavior using a fake repository. Integration testing with a running Cassandra cluster is still required.
