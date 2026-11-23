package acl

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// Role bit values match Temporal's RoleWorker, RoleReader, RoleWriter, RoleAdmin.
type Role uint8

const (
	RoleWorker Role = 1 << iota
	RoleReader
	RoleWriter
	RoleAdmin
)

type Identity struct {
	UserID   string
	UserType string
}
type Permissions map[string]Role

var ErrInvalidIdentity = errors.New("invalid ACL identity")

type PermissionModel interface {
	GetPermissions(ctx context.Context, user Identity) (Permissions, error)
	Close() error
}

type repository interface {
	UserExists(ctx context.Context, user Identity) (bool, error)
	DirectPermissions(ctx context.Context, user Identity) ([]Grant, error)
	UserGroups(ctx context.Context, user Identity) ([]string, error)
	GroupPermissions(ctx context.Context, group string) ([]Grant, error)
	Close() error
}
type Grant struct {
	Namespace string
	Role      string
}

type Model struct {
	repo      repository
	maxGroups int
}

func newModel(repo repository, maxGroups int) *Model {
	if maxGroups <= 0 {
		maxGroups = 100
	}
	return &Model{repo: repo, maxGroups: maxGroups}
}
func (m *Model) Close() error { return m.repo.Close() }

// GetPermissions never falls back to allow-all, including during database errors.
// No cache: each call reads current ACL state from Cassandra.
func (m *Model) GetPermissions(ctx context.Context, user Identity) (Permissions, error) {
	if strings.TrimSpace(user.UserID) == "" || strings.TrimSpace(user.UserType) == "" {
		return nil, ErrInvalidIdentity
	}
	if user.UserType != "Human" && user.UserType != "SDK" {
		return nil, fmt.Errorf("%w: unsupported user_type %q", ErrInvalidIdentity, user.UserType)
	}
	exists, err := m.repo.UserExists(ctx, user)
	if err != nil {
		return nil, fmt.Errorf("user lookup: %w", err)
	}
	if !exists {
		return Permissions{}, nil
	}
	direct, err := m.repo.DirectPermissions(ctx, user)
	if err != nil {
		return nil, fmt.Errorf("direct permissions: %w", err)
	}
	groups, err := m.repo.UserGroups(ctx, user)
	if err != nil {
		return nil, fmt.Errorf("user groups: %w", err)
	}
	if len(groups) > m.maxGroups {
		return nil, fmt.Errorf("group count %d exceeds max %d", len(groups), m.maxGroups)
	}
	out := make(Permissions)
	if err = merge(out, direct); err != nil {
		return nil, err
	}
	for _, group := range groups {
		if group == "" {
			return nil, errors.New("empty group_id in user_groups")
		}
		grants, qerr := m.repo.GroupPermissions(ctx, group)
		if qerr != nil {
			return nil, fmt.Errorf("group %q permissions: %w", group, qerr)
		}
		if err = merge(out, grants); err != nil {
			return nil, fmt.Errorf("group %q: %w", group, err)
		}
	}
	return out, nil
}
func merge(dst Permissions, grants []Grant) error {
	for _, g := range grants {
		if strings.TrimSpace(g.Namespace) == "" {
			return errors.New("empty namespace in grant")
		}
		role, err := parseRole(g.Role)
		if err != nil {
			return fmt.Errorf("namespace %q: %w", g.Namespace, err)
		}
		dst[g.Namespace] |= role // direct and group grants are additive (bitwise OR).
	}
	return nil
}
func parseRole(s string) (Role, error) {
	switch s {
	case "worker":
		return RoleWorker, nil
	case "read":
		return RoleReader, nil
	case "write":
		return RoleWriter, nil
	case "admin":
		return RoleAdmin, nil
	}
	return 0, fmt.Errorf("unknown role %q", s)
}

// StaticModel is deliberately explicit: use only for test/dev; no implicit fallback.
type StaticModel struct{ ByUser map[Identity]Permissions }

func (s *StaticModel) GetPermissions(_ context.Context, u Identity) (Permissions, error) {
	out := make(Permissions)
	for ns, r := range s.ByUser[u] {
		out[ns] = r
	}
	return out, nil
}
func (*StaticModel) Close() error { return nil }
