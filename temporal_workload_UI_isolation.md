# Temporal Frontend Authentication & Authorization Design

## 1. Background & Design Goals

### 1.1 Background

We are deploying a self-hosted Temporal cluster with two types of clients:

| Client Type | Identity Provider | Token Type | Authentication |
|---|---|---|---|
| Human / UI | Okta OIDC | ID Token (JWT) | Bearer Token |
| Workload / SDK | SPIRE | JWT-SVID | Bearer Token |

Both clients access the same Temporal Frontend through gRPC APIs.

Additional context:
- Workload traffic accounts for the vast majority of requests.
- UI traffic is relatively low.
- Authorization policies are managed centrally through an internal ACL system.
- Both Human and Workload identities should be normalized into a common Principal representation.
- The deployment runs on AWS EKS.
- The design should minimize modifications to Temporal upstream code.

### 1.2 Design Goals

| Goal | Description | Priority |
|---|---|---|
| Unified Authentication Interface | Both Human and Workload use `Authorization: Bearer <token>` | High |
| Independent Authentication | Okta and SPIRE use independent token verification mechanisms | High |
| Failure Isolation | Failure of one authentication provider must not affect the other | **Critical** |
| Workload Availability | Okta outages must not impact Workload requests | **Critical** |
| Unified Authorization | Both identity types use the same ACL Authorizer | High |
| Security | Strict token validation; no cross-provider impersonation or fallback | **Critical** |
| Performance | Local JWT verification without per-request external dependencies | High |
| Maintainability | Minimize modifications to Temporal core code | High |
| Observability | Independent metrics and health monitoring for each provider | Medium |

### 1.3 Non-Goals

The initial design does not aim to:

- Deploy separate Temporal Frontend clusters for Human and Workload traffic.
- Provide process-level or infrastructure-level fault isolation.
- Guarantee that a request carrying a Human Token originated from the UI Server.
- Introduce a separate authorization service for each identity provider.
- Modify the Temporal gRPC API protocol.

The main objective is **Authentication Provider-level failure isolation**, rather than complete infrastructure isolation.

---

## 2. Temporal Authentication & Authorization Architecture

### 2.1 Existing Temporal Extension Points

Temporal provides authentication and authorization extension points through its Frontend authorization interceptor.

Relevant source code:

| Component | Source | Responsibility |
|---|---|---|
| Authorization Interceptor | [interceptor.go](https://github.com/temporalio/temporal/blob/main/common/authorization/interceptor.go) | Extract authentication information and invoke ClaimMapper and Authorizer |
| ClaimMapper Interface | [claim_mapper.go](https://github.com/temporalio/temporal/blob/main/common/authorization/claim_mapper.go) | Convert authentication information into Claims |
| Default JWT ClaimMapper | [default_jwt_claim_mapper.go](https://github.com/temporalio/temporal/blob/main/common/authorization/default_jwt_claim_mapper.go) | Reference JWT validation and claim mapping implementation |
| Authorizer Interface | [authorizer.go](https://github.com/temporalio/temporal/blob/main/common/authorization/authorizer.go) | Make authorization decisions |
| Temporal UI Server | [ui-server](https://github.com/temporalio/ui-server) | OIDC login and token forwarding |

Conceptually, the existing authentication and authorization flow is:

```text
Client
  |
  | gRPC Authorization: Bearer <JWT>
  v
Temporal Frontend
  |
  v
Authorization Interceptor
  |
  +-- ClaimMapper.GetClaims(AuthInfo)
  |       |
  |       +-- Token validation
  |       +-- Identity extraction
  |       +-- Claims mapping
  |
  +-- Authorizer.Authorize(Claims, CallTarget)
          |
          +-- ACL evaluation
          +-- Allow / Deny
```

Temporal normally injects a single ClaimMapper implementation into the authorization interceptor.

Therefore, supporting multiple authentication providers requires either:
1. A single ClaimMapper that supports multiple verifiers.
2. A routing ClaimMapper that delegates to independent ClaimMapper implementations.
3. Modifications to the interceptor to support multiple ClaimMappers directly.

---

## 3. Candidate Designs

### 3.1 Option A: Single ClaimMapper with Multiple Verifiers

Architecture:

```text
Authorization Interceptor
         |
         v
MultiProviderClaimMapper
         |
         +-- OktaVerifier
         |
         +-- SpireVerifier
         |
         v
Unified Claims
         |
         v
ACL Authorizer
```

The ClaimMapper is responsible for:
- Determining token issuer.
- Selecting the appropriate verifier.
- Validating the token.
- Extracting identity.
- Mapping identity to Claims.

Advantages:
- Simple architecture.
- Minimal code changes.
- Single implementation to register with Temporal.

Disadvantages:
- Authentication and identity mapping logic for different providers are coupled.
- Larger implementation with multiple responsibilities.
- Independent testing and maintenance become more complicated.
- Provider-specific lifecycle management requires additional internal separation.

### 3.2 Option B: RoutingClaimMapper + Independent ClaimMappers (Recommended)

Architecture:

```text
                         Temporal Frontend
                                |
                                v
                       Authorization Interceptor
                                |
                                v
                        RoutingClaimMapper
                                |
                   +------------+------------+
                   |                         |
                   v                         v
             OktaClaimMapper           SpireClaimMapper
                   |                         |
                   v                         v
              Okta Verifier             SPIRE Verifier
                   |                         |
                   v                         v
              Human Claims             Workload Claims
                   |                         |
                   +------------+------------+
                                |
                                v
                        Unified ACL Authorizer
                                |
                                v
                         Temporal API
```

Each ClaimMapper independently handles:
- Token validation.
- Provider-specific claims.
- Identity extraction.
- Principal normalization.
- Provider-specific caches and dependencies.

RoutingClaimMapper only:
1. Extracts the token.
2. Determines the candidate identity provider.
3. Delegates to the corresponding ClaimMapper.

Advantages:
- Clear separation between Human and Workload authentication.
- Independent public-key caching and refresh.
- Independent timeout and error handling.
- Easier provider-specific testing.
- Minimal Temporal upstream modifications.
- Easy to add additional authentication providers later.
- Supports authentication provider-level failure isolation.

Disadvantages:
- Requires a small routing implementation.
- Both providers still share the same Frontend process.
- Shared Frontend failures cannot be fully isolated.

### 3.3 Option C: Separate Frontend Deployments

Architecture:

```text
Human / UI
    |
    v
Human Frontend Deployment
    |
    v
OktaClaimMapper
    |
    v
Unified ACL


Workload / SDK
    |
    v
Workload Frontend Deployment
    |
    v
SpireClaimMapper
    |
    v
Unified ACL
```

Both Frontend deployments connect to the same underlying Temporal cluster.

Advantages:
- Stronger process-level isolation.
- Independent resource allocation and scaling.
- UI authentication failures are less likely to impact Workload availability.
- Separate ingress and networking policies.

Disadvantages:
- Higher deployment and operational complexity.
- Additional infrastructure costs.
- More complicated configuration management.
- Shared dependencies such as ACL, History, Matching, and persistence still exist.
- Requires care to maintain compatible Frontend behavior and configuration.

### 3.4 Comparison

| Dimension | Option A: Single Mapper | Option B: Two Mappers + Router | Option C: Separate Frontends |
|---|---|---|---|
| Implementation complexity | Low | Low–Medium | High |
| Authentication logic isolation | Medium | **High** | High |
| Provider dependency isolation | Possible | **High** | High |
| Process-level isolation | No | No | Yes |
| Independent public-key cache | Yes | Yes | Yes |
| Independent testing | Medium | **High** | High |
| Operational complexity | Low | **Low** | High |
| Workload protection from Okta outages | Yes, if correctly implemented | **Yes, if correctly implemented** | Yes, with independent dependencies |
| Resource isolation | No | No | Yes |
| Temporal core modifications | Minimal | **Minimal** | Depends on deployment configuration |

**Recommendation: Option B — RoutingClaimMapper + two independent ClaimMappers.**

Given the relatively low UI traffic and high Workload traffic, separate Frontend deployments are not necessary at this stage.

---

## 4. Recommended Detailed Design

### 4.1 RoutingClaimMapper

The Router selects the appropriate ClaimMapper based on the JWT issuer.

Conceptual implementation:

```go
type RoutingClaimMapper struct {
    oktaMapper  authorization.ClaimMapper
    spireMapper authorization.ClaimMapper
}

func (m *RoutingClaimMapper) GetClaims(
    authInfo *authorization.AuthInfo,
) (*authorization.Claims, error) {

    token := authInfo.AuthToken

    issuer, err := peekIssuer(token)
    if err != nil {
        return nil, err
    }

    switch issuer {
    case oktaIssuer:
        return m.oktaMapper.GetClaims(authInfo)

    case spireIssuer:
        return m.spireMapper.GetClaims(authInfo)

    default:
        return nil, ErrUnknownIssuer
    }
}
```

Note: This is conceptual code. Exact interfaces, token extraction and constructors should be adapted to the pinned Temporal Server version.

Security requirements:

- The issuer extracted by `peekIssuer()` is untrusted.
- It must only be used to select a candidate verifier.
- Each ClaimMapper must independently validate the token signature and all required claims.
- A failed verification must not fall back to another provider.
- Unknown issuers must be rejected.
- Token-supplied `jku`, `x5u`, or similar key URLs must not be trusted.
- JWT algorithms must be explicitly allowlisted.
- Token size and parsing complexity should be bounded to prevent resource abuse.

A client cannot gain Human or Workload privileges simply by modifying the unverified `iss` claim.

### 4.2 OktaClaimMapper

Responsibilities:

1. Validate the Okta ID Token signature.
2. Validate issuer.
3. Validate audience.
4. Validate expiration and other relevant time-based claims.
5. Extract a stable Okta User ID.
6. Convert the verified identity into normalized Claims.

Example input:

```json
{
  "iss": "https://company.oktapreview.com/oauth2/default",
  "sub": "00u123abc",
  "aud": "temporal-ui-client-id",
  "exp": 1790000000
}
```

Example normalized identity:

```text
Type: human
Issuer: https://company.oktapreview.com/oauth2/default
Subject: 00u123abc
Principal: okta:00u123abc
```

Implementation considerations:

- Use an explicit list of trusted Okta issuers.
- DEV and PROD issuers must be configured independently.
- Validate the expected OIDC Client ID as the ID Token audience.
- Use the Okta `sub` claim rather than email as the stable user identifier.
- Do not rely on email alone for authorization.
- Use a dedicated JWKS cache and refresh mechanism.

**Security note:** An Okta ID Token is normally issued to an OIDC client, not specifically intended as an API access token. Accepting it at Temporal Frontend is a deliberate custom trust decision. The design must strictly constrain accepted issuers and client IDs, and account for the fact that possession of the bearer token permits replay until expiration. An API-specific Access Token is generally the cleaner alternative.

### 4.3 SpireClaimMapper

Responsibilities:

1. Validate the SPIRE JWT-SVID signature.
2. Validate the trusted JWT issuer.
3. Validate the expected audience.
4. Validate expiration.
5. Validate the SPIFFE ID and trust domain.
6. Extract a normalized Workload identity.

Example input:

```json
{
  "sub": "spiffe://corp.example/ns/payment/sa/order-worker",
  "aud": [
    "temporal-frontend"
  ],
  "exp": 1790000000
}
```

The example omits the JWT-SVID issuer and signature for brevity; the actual token must contain and satisfy the required JWT-SVID claims and signature validation.

Example normalized identity:

```text
Type: workload
Subject: spiffe://corp.example/ns/payment/sa/order-worker
Principal: spiffe://corp.example/ns/payment/sa/order-worker
```

Requirements:

- Accept JWT-SVID, not X.509-SVID, for the Bearer Token path.
- Verify the JWT using the configured trusted SPIRE JWT signing keys.
- Validate the required SPIFFE Trust Domain.
- Use a dedicated audience for Temporal Frontend.
- Reject identities from untrusted trust domains.
- Use locally cached JWT signing keys.
- Avoid remote SPIRE calls for every gRPC request.

The Workload is responsible for acquiring and refreshing its JWT-SVID before expiration.

### 4.4 Principal Normalization

Both ClaimMappers produce a common identity representation.

Recommended conceptual structure:

```go
type Principal struct {
    Type    string // human or workload
    Issuer  string
    Subject string
    ID      string
}
```

Examples:

| Field | Human | Workload |
|---|---|---|
| Type | human | workload |
| Issuer | Okta Issuer | SPIRE JWT Issuer |
| Subject | Okta User ID | SPIFFE ID |
| ID | Issuer-scoped Okta User ID | SPIFFE ID |

The internal Principal ID should avoid collisions across different Okta organizations or identity providers.

For example, the DEV and PROD Okta organizations may have different users with similar identifiers. Their complete verified identities must remain distinct.

When mapping to Temporal's `authorization.Claims`, preserve enough information for the Authorizer to distinguish:
- Human vs. Workload.
- Verified issuer.
- Stable subject identifier.

Do not assume the built-in Claims structure exactly matches the conceptual Principal structure; adapt the mapping to the Temporal version being deployed.

### 4.5 Unified ACL Authorizer

The Authorizer receives normalized identity information and the requested Temporal API operation.

Conceptual interface:

```go
ACL.Check(
    principal,
    namespace,
    api,
)
```

Example:

```text
Principal:
    okta:00u123abc

Request:
    namespace = payment
    api = ListWorkflowExecutions

Result:
    ALLOW
```

Another example:

```text
Principal:
    spiffe://corp.example/ns/payment/sa/order-worker

Request:
    namespace = payment
    api = StartWorkflowExecution

Result:
    ALLOW
```

Design principles:

- Authentication and authorization are separate responsibilities.
- ClaimMapper verifies identity and normalizes Claims.
- Authorizer evaluates ACL permissions.
- ACL policies should be independent of the token verification mechanism.
- Human and Workload can have different ACL policies.
- Default authorization behavior must be Deny.
- Invalid or missing identity information must not result in elevated permissions.

The implementation must also define how namespace-less and cluster-level APIs are authorized, rather than assuming every Temporal API has a namespace.

A centrally managed ACL policy can be distributed to Frontend instances and evaluated locally.

This avoids requiring a remote ACL request for every high-volume Workload RPC.

---

## 5. Authentication Provider Failure Isolation

### 5.1 Isolation Scope

The primary requirement is:

**Failure of Okta authentication must not impact SPIRE authentication, and vice versa.**

However, this only covers authentication provider-level failures.

| Failure Scenario | Human Requests | Workload Requests | Isolation Expected |
|---|---|---|---|
| Okta unavailable | May fail for new/uncached keys or login | Unaffected | Yes |
| Okta JWKS refresh failure | May fail if no valid cached key | Unaffected | Yes |
| Okta token verification failure | Rejected | Unaffected | Yes |
| SPIRE JWT Bundle refresh failure | Unaffected | May fail if no valid cached key | Yes |
| SPIRE unavailable | Usually unaffected | New token acquisition may fail | Yes |
| OktaClaimMapper initialization failure | May be unavailable | Unaffected | Yes |
| SpireClaimMapper initialization failure | Unaffected | May be unavailable | Yes |
| Frontend process crash | Affected | Affected | No |
| Shared ACL failure | Affected | Affected | No |
| Frontend CPU exhaustion | May be affected | May be affected | No |

### 5.2 Independent Provider Dependencies

Each ClaimMapper should maintain independent state:

| Component | OktaClaimMapper | SpireClaimMapper |
|---|---|---|
| Public-key source | Okta JWKS | SPIRE JWT Bundle |
| Public-key cache | Independent | Independent |
| Background refresh | Independent | Independent |
| Network timeout | Independent | Independent |
| Retry policy | Independent | Independent |
| Error handling | Independent | Independent |
| Metrics | Independent | Independent |
| Readiness state | Independent | Independent |

Avoid:
- A single global key cache with mutable provider configuration.
- A global lock that blocks both providers during key refresh.
- Synchronous external key retrieval on every request.
- A shared external-provider initialization dependency.
- Any verification fallback that weakens identity checks.

### 5.3 Local Token Verification

Recommended request path:

```text
Workload Request
    |
    v
RoutingClaimMapper
    |
    v
SpireClaimMapper
    |
    v
Local JWT Signature Verification
    |
    v
Normalized Claims
    |
    v
Local ACL Evaluation
    |
    v
Temporal API Handler
```

The steady-state Workload request path should not depend on:
- Okta availability.
- Okta JWKS endpoint.
- SPIRE Server availability for each individual request.
- An external ACL service for each individual request.

This is particularly important because Workload requests represent the majority of Frontend traffic.

### 5.4 Public-Key Cache and Refresh

Recommended mechanism:

1. Load trusted public keys from an independent cache or trusted bootstrap source.
2. Verify requests using locally available keys.
3. Refresh keys asynchronously.
4. Use bounded retries and timeouts.
5. Ensure one provider's key refresh does not block the other.
6. Reject tokens when no valid trusted verification key is available.

Additional requirements:

- Support signing-key rotation.
- Define bounded stale-key retention policies.
- Avoid unlimited use of old keys after revocation or trust changes.
- Handle unknown `kid` using rate-limited, deduplicated refresh attempts.
- Ensure malformed tokens cannot trigger arbitrary network requests.
- Monitor key age and last successful refresh time.

**Important:** Provider availability must not be achieved by skipping signature verification or accepting unknown signing keys.

### 5.5 Frontend Startup Behavior

A key risk is coupling Frontend availability to remote authentication providers.

Avoid:

```go
func NewRoutingClaimMapper() (*RoutingClaimMapper, error) {
    oktaKeys := FetchOktaJWKS() // Failure aborts startup
    spireKeys := FetchSpireKeys()

    return NewRoutingClaimMapper(oktaKeys, spireKeys), nil
}
```

Recommended behavior:

```text
Frontend Startup
    |
    +-- Initialize OktaClaimMapper
    |       |
    |       +-- Load trusted cached keys, if available
    |       +-- Start independent JWKS refresh
    |
    +-- Initialize SpireClaimMapper
    |       |
    |       +-- Load trusted cached keys, if available
    |       +-- Start independent JWT Bundle refresh
    |
    v
Frontend Ready for Supported Requests
```

Startup requirements:

- Okta unavailability must not prevent the SPIRE authentication path from starting.
- SPIRE unavailability must not prevent the Okta authentication path from starting.
- If a provider lacks valid verification keys, reject requests associated with that provider.
- Provider-specific failures must not terminate the Frontend process.
- Core Frontend readiness and provider-specific readiness should be monitored separately.

Because Workload availability is the priority, deployment readiness and rollout policy should be tested carefully when the SPIRE verifier is unavailable.

Avoid marking an instance fully healthy solely because the process is alive if its Workload authentication path is not operational.

---

## 6. Security Considerations

### 6.1 Bearer Token Does Not Prove Request Origin

Both types of clients use:

```http
Authorization: Bearer <JWT>
```

The Frontend can distinguish the verified identity provider and identity type.

However, a Bearer Token only proves possession of the token.

It does not prove that:
- A Human token was sent by the official Temporal UI Server.
- A Workload token was sent by a particular executable binary.
- The caller is the original recipient of the token.

For example, a Workload or custom CLI possessing a valid Okta ID Token may be able to authenticate as the corresponding Human identity.

Potential additional protections include:
- Network-level restrictions.
- Separate ingress policies.
- Short-lived tokens.
- Token audience restrictions.
- mTLS or sender-constrained tokens where needed.

These protections are optional extensions depending on the desired threat model.

### 6.2 Strict Provider Separation

Security rules:

1. Okta tokens must only be accepted by OktaClaimMapper.
2. SPIRE tokens must only be accepted by SpireClaimMapper.
3. Each mapper must enforce its configured issuer and audience.
4. Each mapper must use its own trusted signing keys.
5. A failed verification must not fall back to another provider.
6. Unknown identity providers must be rejected.
7. Unverified token claims must never be used for ACL authorization.
8. Human and Workload identities must occupy distinct logical identity namespaces.

### 6.3 Token Expiration

The two authentication systems have independent token lifecycles.

| Aspect | Okta ID Token | SPIRE JWT-SVID |
|---|---|---|
| Issuer | Okta | SPIRE |
| Token acquisition | OIDC login | SPIFFE Workload API |
| Token refresh | OIDC refresh/re-login mechanisms | Obtain a new JWT-SVID |
| Validation | Local JWT verification | Local JWT verification |
| Expiration enforcement | Required | Required |
| External dependency per request | Not required | Not required |

A provider outage should not automatically invalidate already issued tokens if they remain valid and can be verified using trusted cached keys.

However, expired tokens must still be rejected.

### 6.4 ACL Security

The unified ACL system must preserve the verified identity type.

For example:

```text
human:okta:<issuer>:<subject>
workload:<spiffe-id>
```

These are conceptual identifiers; use a canonical encoding to avoid ambiguous separators or collisions.

The ACL must not treat Human and Workload as equivalent merely because they have matching names or labels.

---

## 7. Performance Considerations

Since Workload traffic is the dominant traffic type, performance optimization should focus on the SPIRE authentication path.

| Component | Potential Overhead | Recommendation |
|---|---|---|
| RoutingClaimMapper | JWT parsing and issuer lookup | Lightweight parsing with bounded token sizes |
| SPIRE JWT verification | Cryptographic signature verification | Local verification, benchmark under production-like QPS |
| SPIRE key refresh | Network and key parsing | Background asynchronous refresh |
| Principal normalization | Small allocation and string processing | Keep implementation simple |
| ACL lookup | Policy evaluation | Prefer local immutable policy snapshots or cache |
| Logging | Per-request log overhead | Avoid verbose success logs at high QPS |

Recommended principles:

- Do not introduce network calls into the Workload authentication hot path.
- Avoid global locks shared between providers.
- Avoid excessive object allocations.
- Benchmark end-to-end Frontend authentication overhead.
- Monitor p50/p95/p99 latency.
- Ensure authorization and audit logging do not become bottlenecks.

Signature verification should not be skipped merely for performance.

---

## 8. Testing Plan

### 8.1 Functional Tests

| Test Case | Expected Result |
|---|---|
| Valid Okta ID Token | Authenticated as Human |
| Valid SPIRE JWT-SVID | Authenticated as Workload |
| Unknown JWT issuer | Rejected |
| Invalid JWT signature | Rejected |
| Expired JWT | Rejected |
| Wrong audience | Rejected |
| Wrong issuer | Rejected |
| Token from untrusted SPIFFE Trust Domain | Rejected |
| Malformed JWT | Rejected |
| Missing Bearer Token on protected API | Rejected |
| Okta JWT sent to SpireClaimMapper | Rejected |
| SPIRE JWT sent to OktaClaimMapper | Rejected |
| Valid identity with insufficient ACL | Permission denied |
| Valid identity with sufficient ACL | Allowed |

### 8.2 Failure Isolation Tests (Critical)

These are the most important tests for the design.

| Test | Failure Injection | Expected Result |
|---|---|---|
| F1 | Block access to Okta JWKS Endpoint | Existing valid SPIRE JWT-SVID requests continue |
| F2 | Okta JWKS endpoint returns HTTP 500 | Workload requests remain unaffected |
| F3 | Okta JWKS endpoint responds slowly | SPIRE requests do not wait for Okta |
| F4 | Okta JWKS returns malformed JSON | SPIRE authentication remains functional |
| F5 | SPIRE key refresh unavailable | Okta authentication remains functional |
| F6 | SPIRE JWT Bundle malformed | Okta authentication remains functional |
| F7 | Start Frontend while Okta is unreachable | SPIRE authentication path remains available |
| F8 | Restore Okta connectivity | Okta authentication recovers without Frontend restart |
| F9 | Trigger an unknown Okta signing key | SPIRE requests remain unaffected |
| F10 | Concurrent Okta key refresh failures | No shared lock contention affecting SPIRE |

For F5, existing valid SPIRE tokens may continue to work if trusted cached signing keys remain available.

The tests must explicitly verify that SPIRE token verification never bypasses cryptographic validation.

### 8.3 Security Tests

Test the following cases:

- Modify JWT `iss` without resigning the token.
- Modify JWT `sub` without resigning the token.
- Change JWT `aud`.
- Use an unexpected signing algorithm.
- Use an unknown `kid`.
- Include a malicious `jku` or `x5u` URL.
- Use a JWT signed by another trusted-but-unrelated provider.
- Use tokens from a different Okta organization.
- Use JWT-SVIDs from an untrusted SPIFFE Trust Domain.
- Attempt cross-provider identity impersonation.
- Attempt ACL privilege escalation through token claims.
- Submit oversized or deeply malformed JWTs.
- Attempt to exploit key refresh behavior with large numbers of unknown key IDs.

Expected result: Reject invalid tokens without affecting other requests or causing unbounded resource consumption.

### 8.4 Performance Tests

Benchmark at realistic Workload QPS.

Recommended measurements:

| Metric | Purpose |
|---|---|
| Authentication latency p50/p95/p99 | Measure verification cost |
| Frontend CPU utilization | Estimate signature verification overhead |
| Frontend memory utilization | Detect allocation or cache problems |
| Authentication throughput | Determine sustainable QPS |
| ACL evaluation latency | Detect authorization bottlenecks |
| JWT verification failures | Detect authentication issues |
| Cache refresh duration | Monitor external key dependencies |

Recommended workload scenarios:

1. 100% SPIRE traffic.
2. 99% SPIRE + 1% Okta traffic.
3. SPIRE traffic during Okta JWKS failure.
4. SPIRE traffic during repeated invalid Okta token requests.
5. High-concurrency Workload requests during SPIRE key refresh.
6. Workload traffic during ACL policy updates.

For failure-isolation performance tests, compare Workload throughput and latency against a healthy baseline.

Ideally, Okta failures should have no material effect on Workload p99 latency or throughput.

### 8.5 Deployment and Upgrade Tests

Additional tests:

- Frontend rolling restart while Okta is unavailable.
- Frontend rolling restart while SPIRE is unavailable.
- Signing-key rotation during rolling deployment.
- ACL policy update during active requests.
- Expired cached signing keys.
- Temporal Server upgrade compatibility.
- Multiple Frontend replicas with different key-refresh times.
- Recovery after transient DNS, TLS, or network failures.

---

## 9. Observability

Monitor the two authentication providers independently.

Suggested custom metrics:

| Metric | Labels | Description |
|---|---|---|
| `auth_requests_total` | provider, result | Authentication request count |
| `auth_verify_duration_seconds` | provider | JWT verification latency |
| `auth_verify_failures_total` | provider, reason | Verification failures |
| `auth_key_refresh_total` | provider, result | Signing-key refresh attempts |
| `auth_key_refresh_duration_seconds` | provider | Refresh latency |
| `auth_key_last_success_timestamp_seconds` | provider | Last successful key refresh |
| `auth_provider_ready` | provider | Whether provider can validate tokens |
| `acl_requests_total` | principal_type, result | ACL decision count |
| `acl_duration_seconds` | principal_type | ACL evaluation latency |

Avoid putting raw JWTs, full Human IDs, or high-cardinality SPIFFE IDs into metric labels.

For logs, record:
- Authentication provider.
- Failure category.
- Requested Temporal API.
- Namespace, where applicable.
- Request correlation ID.

Do not log:
- Raw JWT tokens.
- Client secrets.
- Refresh tokens.
- Sensitive token contents.

Suggested alerts:

- SPIRE verifier unavailable.
- SPIRE key refresh consistently failing.
- Workload authentication failure rate increasing.
- Workload authentication p99 latency increasing.
- Okta verifier unavailable.
- ACL evaluation errors increasing.

SPIRE-related alerts should generally receive higher operational priority because Workload availability is critical.

---

## 10. Implementation Strategy

### Phase 1: Authentication Integration

Implement:

- RoutingClaimMapper.
- OktaClaimMapper.
- SpireClaimMapper.
- Strict JWT issuer/audience validation.
- Principal normalization.
- Unified ACL Authorizer.

Keep Temporal Authorization Interceptor unchanged if the existing extension points are sufficient.

### Phase 2: Failure Isolation

Implement:

- Independent public-key caches.
- Asynchronous key refresh.
- Provider-specific timeout and retry configuration.
- Non-blocking provider initialization.
- Provider-specific failure metrics.
- Provider-specific health status.

Validate that Okta failures do not affect Workload traffic.

### Phase 3: Production Hardening

Implement:

- Key rotation tests.
- Security and malformed-token tests.
- Performance benchmarks.
- Failure injection tests.
- Rolling deployment tests.
- Operational dashboards and alerts.

### Phase 4: Optional Future Improvements

If stronger isolation becomes necessary:

- Separate Human and Workload ingress.
- Separate Frontend deployments.
- Dedicated resources for Workload Frontend.
- Additional sender-constrained token mechanisms.
- More granular authentication rate limiting.

These improvements are not required for the initial design.

---

## 11. Final Recommendation

**Adopt Option B: RoutingClaimMapper + two independent ClaimMappers + a unified ACL Authorizer.**

The design achieves:

1. **Unified interface:** Human and Workload use Bearer JWT authentication.
2. **Independent verification:** Okta and SPIRE use separate verification logic and signing keys.
3. **Provider-level failure isolation:** Problems in one identity provider do not inherently impact the other.
4. **Unified authorization:** A common ACL system evaluates normalized identities.
5. **Workload-first performance:** SPIRE verification and ACL evaluation remain local in the request hot path.
6. **Low maintenance cost:** Existing Temporal authentication and authorization extension points are reused.

Key architectural constraints:

- No per-request network dependency for JWT signature verification.
- No shared key-refresh lock or synchronous provider dependency.
- No provider fallback after token validation failure.
- No authentication bypass when verification keys are unavailable.
- No Frontend-wide startup failure caused solely by Okta unavailability.
- No assumption that a Bearer Token proves the identity of the calling application.

### Acceptance Criteria

The design can be considered successful when:

- Valid Human and Workload tokens are authenticated and authorized correctly.
- Cross-provider impersonation attempts fail.
- Okta outages do not prevent Workload requests from succeeding.
- Okta JWKS failures do not materially degrade Workload p99 latency or throughput.
- SPIRE authentication operates without remote calls on the per-request verification path.
- Frontend rolling restarts do not introduce an Okta dependency into Workload availability.
- ACL policies correctly distinguish Human and Workload principals.
- Authentication provider health and errors are independently observable.

**The core principle is to isolate authentication provider dependencies while keeping the Temporal Frontend and ACL architecture unified.**

---

## 12. References

### Temporal

- [Temporal Server Repository](https://github.com/temporalio/temporal)
- [Temporal Authorization Interceptor](https://github.com/temporalio/temporal/blob/main/common/authorization/interceptor.go)
- [Temporal ClaimMapper](https://github.com/temporalio/temporal/blob/main/common/authorization/claim_mapper.go)
- [Temporal Default JWT ClaimMapper](https://github.com/temporalio/temporal/blob/main/common/authorization/default_jwt_claim_mapper.go)
- [Temporal Authorizer](https://github.com/temporalio/temporal/blob/main/common/authorization/authorizer.go)
- [Temporal UI Server](https://github.com/temporalio/ui-server)

### SPIFFE / SPIRE

- [SPIFFE JWT-SVID Specification](https://github.com/spiffe/spiffe/blob/main/standards/JWT-SVID.md)
- [SPIFFE Workload API Specification](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Workload_API.md)
- [SPIRE Documentation](https://spiffe.io/docs/latest/spire-about/)

### Okta / OIDC

- [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html)
- [OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)
- [Okta OAuth 2.0 and OpenID Connect](https://developer.okta.com/docs/concepts/oauth-openid/)
