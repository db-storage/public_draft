package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

type Input struct {
	Operations []Operation `json:"operations"`
}
type Operation struct {
	Table  string          `json:"table"`
	Action string          `json:"action"`
	Data   json.RawMessage `json:"data,omitempty"`
	Key    json.RawMessage `json:"key,omitempty"`
	Row    Row             `json:"-"`
}

func strictJSON(data []byte, dest any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(dest); err != nil {
		return err
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return fmt.Errorf("trailing JSON content")
	}
	return nil
}
func loadInput(path string) (Input, error) {
	var in Input
	b, err := os.ReadFile(path)
	if err != nil {
		return in, err
	}
	if err := strictJSON(b, &in); err != nil {
		return in, err
	}
	if len(in.Operations) == 0 {
		return in, fmt.Errorf("operations must not be empty")
	}
	for i := range in.Operations {
		op := &in.Operations[i]
		t, ok := tables[op.Table]
		if !ok {
			return in, fmt.Errorf("operation %d: unsupported table %q", i+1, op.Table)
		}
		if op.Action != "upsert" && op.Action != "delete" {
			return in, fmt.Errorf("operation %d: action must be upsert or delete", i+1)
		}
		if op.Action == "upsert" && len(op.Key) > 0 {
			return in, fmt.Errorf("operation %d: upsert uses data, not key", i+1)
		}
		if op.Action == "delete" && len(op.Data) > 0 {
			return in, fmt.Errorf("operation %d: delete uses key, not data", i+1)
		}
		raw := op.Data
		if op.Action == "delete" {
			raw = op.Key
		}
		if len(raw) == 0 {
			return in, fmt.Errorf("operation %d: missing data/key", i+1)
		}
		// Map raw messages so there is no implicit float64 conversion or silent unknown columns.
		var object map[string]json.RawMessage
		if err := strictJSON(raw, &object); err != nil {
			return in, fmt.Errorf("operation %d: %w", i+1, err)
		}
		if len(object) == 0 {
			return in, fmt.Errorf("operation %d: empty data/key", i+1)
		}
		op.Row = Row{}
		for col, value := range object {
			typ, exists := t.Columns[col]
			if !exists {
				return in, fmt.Errorf("operation %d: unknown column %s.%s", i+1, t.Name, col)
			}
			if op.Action == "delete" && !keyColumns(t)[col] {
				return in, fmt.Errorf("operation %d: delete key contains non-PK field %s", i+1, col)
			}
			if bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
				if keyColumns(t)[col] {
					return in, fmt.Errorf("operation %d: null PK %s", i+1, col)
				}
				op.Row[col] = nil
				continue
			}
			var s string
			if err := strictJSON(value, &s); err != nil {
				return in, fmt.Errorf("operation %d: field %s must be JSON string (timestamp RFC3339): %w", i+1, col, err)
			}
			if keyColumns(t)[col] && strings.TrimSpace(s) == "" {
				return in, fmt.Errorf("operation %d: empty PK %s", i+1, col)
			}
			if typ == "timestamp" {
				ts, err := time.Parse(time.RFC3339Nano, s)
				if err != nil {
					return in, fmt.Errorf("operation %d: %s invalid RFC3339 timestamp: %w", i+1, col, err)
				}
				op.Row[col] = ts.UTC()
			} else {
				if col == "user_type" && s != "Human" && s != "SDK" {
					return in, fmt.Errorf("operation %d: user_type must be Human or SDK", i+1)
				}
				if col == "role_name" && s != "read" && s != "write" && s != "worker" && s != "admin" {
					return in, fmt.Errorf("operation %d: invalid role_name %q", i+1, s)
				}
				op.Row[col] = s
			}
		}
		if _, err := keyValues(t, op.Row); err != nil {
			return in, fmt.Errorf("operation %d: %w", i+1, err)
		}
		if op.Action == "upsert" && (op.Table == "group_members" || op.Table == "user_groups") {
			// added_at belongs to group_members only; both tables otherwise share the three key columns.
		}
	}
	return in, nil
}
