//go:build temporal

// Integration adapter: compile inside the Temporal source tree, or add the matching
// go.temporal.io/server dependency and build with -tags temporal.
package temporaladapter

import (
	"context"
	"errors"
	"time"

	"example.com/temporal-acl/acl"
	"go.temporal.io/server/common/authorization"
)

// IdentityResolver MUST authenticate the credential (JWT signature, iss/aud/exp,
// or SPIFFE SVID trust chain). It must NOT trust unverified JWT payload claims.
type IdentityResolver func(info *authorization.AuthInfo) (acl.Identity, string, error)

type Mapper struct {
	Model   acl.PermissionModel
	Resolve IdentityResolver
	Timeout time.Duration
}

var _ authorization.ClaimMapper = (*Mapper)(nil)

func (m *Mapper) GetClaims(info *authorization.AuthInfo) (*authorization.Claims, error) {
	if m.Model == nil || m.Resolve == nil {
		return nil, errors.New("ACL mapper unconfigured")
	}
	user, authType, err := m.Resolve(info)
	if err != nil {
		return nil, err
	}
	timeout := m.Timeout
	if timeout <= 0 {
		timeout = 500 * time.Millisecond
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	permissions, err := m.Model.GetPermissions(ctx, user)
	if err != nil {
		return nil, err
	}
	namespaces := make(map[string]authorization.Role, len(permissions))
	for ns, role := range permissions {
		namespaces[ns] = authorization.Role(role)
	}
	return &authorization.Claims{Subject: user.UserID, AuthType: authType, Namespaces: namespaces}, nil
}
