package main

import (
	"fmt"
	"sort"
	"strings"

	gocql "github.com/apache/cassandra-gocql-driver/v2"
)

type Statement struct {
	CQL  string
	Args []any
}

type Store interface {
	Get(t Table, key Row) (Row, bool, error)
	Execute(ops []Statement) error
	CAS(stmt Statement) (bool, error)
}

type CassandraStore struct{ session *gocql.Session }

func openStore(hosts, username, password string, port int) (*CassandraStore, error) {
	cluster := gocql.NewCluster(strings.Split(hosts, ",")...)
	cluster.Port = port
	cluster.Consistency = gocql.LocalQuorum
	if username != "" {
		cluster.Authenticator = gocql.PasswordAuthenticator{Username: username, Password: password}
	}
	session, err := cluster.CreateSession()
	if err != nil {
		return nil, err
	}
	return &CassandraStore{session: session}, nil
}
func (s *CassandraStore) Close() { s.session.Close() }
func (s *CassandraStore) Get(t Table, key Row) (Row, bool, error) {
	keys, err := keyValues(t, key)
	if err != nil {
		return nil, false, err
	}
	cols := orderedColumns(t)
	query := fmt.Sprintf("SELECT %s FROM tata.%s WHERE %s", strings.Join(cols, ", "), t.Name, wherePK(t))
	iter := s.session.Query(query, keys...).Iter()
	m := map[string]any{}
	found := iter.MapScan(m)
	if err := iter.Close(); err != nil {
		return nil, false, err
	}
	if !found {
		return nil, false, nil
	}
	row := Row{}
	for _, c := range cols {
		if v, ok := m[c]; ok {
			row[c] = v
		} else {
			row[c] = nil
		}
	}
	return row, true, nil
}
func (s *CassandraStore) Execute(ops []Statement) error {
	if len(ops) == 0 {
		return nil
	}
	if len(ops) == 1 {
		return s.session.Query(ops[0].CQL, ops[0].Args...).Exec()
	}
	batch := s.session.Batch(gocql.LoggedBatch)
	for _, op := range ops {
		batch.Query(op.CQL, op.Args...)
	}
	return batch.Exec()
}
func (s *CassandraStore) CAS(stmt Statement) (bool, error) {
	return s.session.Query(stmt.CQL, stmt.Args...).MapScanCAS(map[string]interface{}{})
}
func insertStmt(t Table, data Row, ifNotExists bool) Statement {
	cols := make([]string, 0, len(data))
	for c := range data {
		cols = append(cols, c)
	}
	sort.Strings(cols)
	values := make([]any, 0, len(cols))
	marks := make([]string, 0, len(cols))
	for _, c := range cols {
		values = append(values, data[c])
		marks = append(marks, "?")
	}
	cql := fmt.Sprintf("INSERT INTO tata.%s (%s) VALUES (%s)", t.Name, strings.Join(cols, ", "), strings.Join(marks, ", "))
	if ifNotExists {
		cql += " IF NOT EXISTS"
	}
	return Statement{cql, values}
}
func deleteStmt(t Table, key Row) Statement {
	vals, _ := keyValues(t, key)
	return Statement{fmt.Sprintf("DELETE FROM tata.%s WHERE %s", t.Name, wherePK(t)), vals}
}
func updateCASStmt(t Table, old Row, incoming Row, changes []Change) Statement {
	sets := make([]string, 0, len(changes))
	cond := make([]string, 0, len(changes))
	args := make([]any, 0, len(changes)*2+len(t.PK))
	for _, ch := range changes {
		sets = append(sets, ch.Column+" = ?")
		args = append(args, ch.New)
	}
	pk, _ := keyValues(t, incoming)
	args = append(args, pk...)
	for _, ch := range changes {
		cond = append(cond, ch.Column+" = ?")
		args = append(args, old[ch.Column])
	}
	cql := fmt.Sprintf("UPDATE tata.%s SET %s WHERE %s IF %s", t.Name, strings.Join(sets, ", "), wherePK(t), strings.Join(cond, " AND "))
	return Statement{cql, args}
}
func deleteCASStmt(t Table, key Row, old Row) Statement {
	keys, _ := keyValues(t, key)
	cond := make([]string, 0)
	args := append([]any{}, keys...)
	for _, col := range orderedColumns(t) {
		if keyColumns(t)[col] {
			continue
		}
		cond = append(cond, col+" = ?")
		args = append(args, old[col])
	}
	cql := fmt.Sprintf("DELETE FROM tata.%s WHERE %s IF %s", t.Name, wherePK(t), strings.Join(cond, " AND "))
	if len(cond) == 0 {
		cql = fmt.Sprintf("DELETE FROM tata.%s WHERE %s IF EXISTS", t.Name, wherePK(t))
	}
	return Statement{cql, args}
}
