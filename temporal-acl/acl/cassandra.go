package acl

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/gocql/gocql"
)

type CassandraConfig struct {
	Hosts            []string `json:"hosts"`
	Keyspace         string   `json:"keyspace"`
	Username         string   `json:"username"`
	Password         string   `json:"password"`
	TimeoutMS        int      `json:"timeout_ms"`
	ConnectTimeoutMS int      `json:"connect_timeout_ms"`
	NumConns         int      `json:"num_conns"`
	MaxGroups        int      `json:"max_groups"`
}

type cassandraRepo struct{ session *gocql.Session }

func NewCassandraModel(cfg CassandraConfig) (PermissionModel, error) {
	if len(cfg.Hosts) == 0 {
		return nil, errors.New("cassandra hosts required")
	}
	if cfg.Keyspace != "tata" {
		return nil, fmt.Errorf("this implementation expects keyspace tata, got %q", cfg.Keyspace)
	}
	cluster := gocql.NewCluster(cfg.Hosts...)
	cluster.Keyspace = cfg.Keyspace
	cluster.Consistency = gocql.LocalQuorum
	if cfg.TimeoutMS <= 0 {
		cfg.TimeoutMS = 500
	}
	if cfg.ConnectTimeoutMS <= 0 {
		cfg.ConnectTimeoutMS = 3000
	}
	if cfg.NumConns <= 0 {
		cfg.NumConns = 2
	}
	cluster.Timeout = time.Duration(cfg.TimeoutMS) * time.Millisecond
	cluster.ConnectTimeout = time.Duration(cfg.ConnectTimeoutMS) * time.Millisecond
	cluster.NumConns = cfg.NumConns
	if cfg.Username != "" {
		cluster.Authenticator = gocql.PasswordAuthenticator{Username: cfg.Username, Password: cfg.Password}
	}
	session, err := cluster.CreateSession()
	if err != nil {
		return nil, fmt.Errorf("connect Cassandra: %w", err)
	}
	return newModel(&cassandraRepo{session: session}, cfg.MaxGroups), nil
}
func (r *cassandraRepo) Close() error { r.session.Close(); return nil }
func (r *cassandraRepo) UserExists(ctx context.Context, user Identity) (bool, error) {
	var id string
	err := r.session.Query(`SELECT user_id FROM users WHERE user_id=? AND user_type=? LIMIT 1`, user.UserID, user.UserType).WithContext(ctx).Scan(&id)
	if errors.Is(err, gocql.ErrNotFound) {
		return false, nil
	}
	return err == nil, err
}
func (r *cassandraRepo) DirectPermissions(ctx context.Context, user Identity) ([]Grant, error) {
	it := r.session.Query(`SELECT namespace,role_name FROM user_permissions WHERE user_id=? AND user_type=?`, user.UserID, user.UserType).WithContext(ctx).Iter()
	var ns, role string
	var out []Grant
	for it.Scan(&ns, &role) {
		out = append(out, Grant{ns, role})
	}
	if err := it.Close(); err != nil {
		return nil, err
	}
	return out, nil
}
func (r *cassandraRepo) UserGroups(ctx context.Context, user Identity) ([]string, error) {
	it := r.session.Query(`SELECT group_id FROM user_groups WHERE user_id=? AND user_type=?`, user.UserID, user.UserType).WithContext(ctx).Iter()
	var group string
	var out []string
	for it.Scan(&group) {
		out = append(out, group)
	}
	if err := it.Close(); err != nil {
		return nil, err
	}
	return out, nil
}
func (r *cassandraRepo) GroupPermissions(ctx context.Context, group string) ([]Grant, error) {
	it := r.session.Query(`SELECT namespace,role_name FROM group_permissions WHERE group_id=?`, group).WithContext(ctx).Iter()
	var ns, role string
	var out []Grant
	for it.Scan(&ns, &role) {
		out = append(out, Grant{ns, role})
	}
	if err := it.Close(); err != nil {
		return nil, err
	}
	return out, nil
}
