
Hi, seems I didn't prioritize it appropriately. I'll prioritize it today and reach Tech Infra Namespace owners one by one, aim to have it completed by tomorrow afternoon. 

Both use Okta for authentication and single sign-on, but the protocols and identity credentials differ: Temporal Cloud uses SAML with XML-based assertions, while the self-hosted Temporal UI uses OIDC with JWT-based ID tokens.
https://docs.temporal.io/cloud/manage-access/saml#how-to-configure-saml-with-okta
https://github.com/temporalio/ui/blob/main/AUTHENTICATION.md?utm_source=chatgpt.com

http://127.0.0.1:8080/callback?code=abc123&state=xyz

| Option | Pros | Cons | Suitable Scenarios |
|---|---|---|---|
| **Shared AD group**: Assign one group to both the Cloud and Self-hosted Okta applications | Reuses existing membership and approval processes; lower maintenance effort | Membership changes affect both applications; access cannot be controlled independently through this group | Identical user populations or temporary coexistence during migration |
| **Separate AD groups**: Assign a dedicated group to each Okta application | Independent access requests, approvals, and revocation; clear access boundaries | Requires maintaining two sets of memberships and approval configurations | Long-term coexistence or different access requirements |

This comparison covers **Okta application sign-in access only**, not Temporal Namespace permissions.
