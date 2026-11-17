package main

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

type Table struct {
	Name    string
	PK      []string
	Columns map[string]string
}

var tables = map[string]Table{
	"users":             {"users", []string{"user_id", "user_type"}, map[string]string{"user_id": "text", "user_type": "text", "cmdb": "text", "created_at": "timestamp"}},
	"groups":            {"groups", []string{"group_id"}, map[string]string{"group_id": "text", "description": "text", "create_at": "timestamp"}},
	"group_members":     {"group_members", []string{"group_id", "user_type", "user_id"}, map[string]string{"group_id": "text", "user_type": "text", "user_id": "text", "added_at": "text"}},
	"user_groups":       {"user_groups", []string{"user_id", "user_type", "group_id"}, map[string]string{"user_id": "text", "user_type": "text", "group_id": "text"}},
	"user_permissions":  {"user_permissions", []string{"user_id", "user_type", "namespace"}, map[string]string{"user_id": "text", "user_type": "text", "namespace": "text", "role_name": "text", "granted_at": "timestamp"}},
	"group_permissions": {"group_permissions", []string{"group_id", "namespace"}, map[string]string{"group_id": "text", "namespace": "text", "role_name": "text", "granted_at": "timestamp"}},
}

func orderedColumns(t Table) []string {
	cols := make([]string, 0, len(t.Columns))
	for col := range t.Columns {
		cols = append(cols, col)
	}
	sort.Strings(cols)
	return cols
}
func keyColumns(t Table) map[string]bool {
	m := make(map[string]bool)
	for _, k := range t.PK {
		m[k] = true
	}
	return m
}
func keyValues(t Table, data Row) ([]any, error) {
	vals := make([]any, 0, len(t.PK))
	for _, k := range t.PK {
		v, ok := data[k]
		if !ok || v == nil || v == "" {
			return nil, fmt.Errorf("%s: missing PK %q", t.Name, k)
		}
		vals = append(vals, v)
	}
	return vals, nil
}
func wherePK(t Table) string {
	cond := make([]string, len(t.PK))
	for i, k := range t.PK {
		cond[i] = k + " = ?"
	}
	return strings.Join(cond, " AND ")
}
func sameValue(a, b any) bool {
	switch av := a.(type) {
	case time.Time:
		bv, ok := b.(time.Time)
		return ok && av.Equal(bv)
	case nil:
		return b == nil
	default:
		return fmt.Sprint(a) == fmt.Sprint(b) && fmt.Sprintf("%T", a) == fmt.Sprintf("%T", b)
	}
}

// Row is a normalized, typed record. Only explicitly supplied columns are written.
type Row map[string]any
