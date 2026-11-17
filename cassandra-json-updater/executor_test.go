package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fakeDB struct {
	rows       map[string]Row
	statements [][]Statement
	casCalls   int
	applied    bool
}

func fakeKey(t Table, key Row) string {
	v, _ := keyValues(t, key)
	parts := []string{t.Name}
	for _, x := range v {
		parts = append(parts, pretty(x))
	}
	return strings.Join(parts, "|")
}
func (f *fakeDB) Get(t Table, key Row) (Row, bool, error) {
	r, ok := f.rows[fakeKey(t, key)]
	return r, ok, nil
}
func (f *fakeDB) Execute(s []Statement) error   { f.statements = append(f.statements, s); return nil }
func (f *fakeDB) CAS(s Statement) (bool, error) { f.casCalls++; return f.applied, nil }
func makeOp(table, action string, row Row) Operation {
	return Operation{Table: table, Action: action, Row: row}
}
func execWith(db *fakeDB, op []Operation, opt Options) (string, error) {
	var b bytes.Buffer
	opt.Writer = &b
	err := NewExecutor(db, opt).Run(op)
	return b.String(), err
}
func TestDiffPartial(t *testing.T) {
	old := Row{"user_id": "alice", "user_type": "Human", "cmdb": "old"}
	got := diff(old, Row{"user_id": "alice", "user_type": "Human", "cmdb": "new"}, tables["users"])
	if len(got) != 1 || got[0].Column != "cmdb" || got[0].Old != "old" || got[0].New != "new" {
		t.Fatalf("bad diff: %#v", got)
	}
	if len(diff(old, Row{"user_id": "alice", "user_type": "Human"}, tables["users"])) != 0 {
		t.Fatal("omitted columns must not change")
	}
}
func TestExistingUnchangedSkip(t *testing.T) {
	op := makeOp("users", "upsert", Row{"user_id": "a", "user_type": "Human", "cmdb": "same"})
	db := &fakeDB{rows: map[string]Row{fakeKey(tables["users"], op.Row): op.Row}, applied: true}
	result, err := execWith(db, []Operation{op}, Options{NonInteractive: true})
	if err != nil || !strings.Contains(result, "SKIP") || db.casCalls != 0 {
		t.Fatalf("result=%s err=%v", result, err)
	}
}
func TestConflictRequiresConfirmation(t *testing.T) {
	op := makeOp("users", "upsert", Row{"user_id": "a", "user_type": "Human", "cmdb": "new"})
	old := Row{"user_id": "a", "user_type": "Human", "cmdb": "old"}
	db := &fakeDB{rows: map[string]Row{fakeKey(tables["users"], op.Row): old}, applied: true}
	output, err := execWith(db, []Operation{op}, Options{NonInteractive: true})
	if err == nil || !strings.Contains(output, "old") || !strings.Contains(output, "new") {
		t.Fatalf("expected diff and noninteractive rejection: %s %v", output, err)
	}
	if db.casCalls != 0 {
		t.Fatal("must not write")
	}
	_, err = execWith(db, []Operation{op}, Options{Reader: strings.NewReader("y\n")})
	if err != nil || db.casCalls != 1 {
		t.Fatalf("expected confirmed CAS update: %v", err)
	}
}
func TestMissingInsertCAS(t *testing.T) {
	op := makeOp("groups", "upsert", Row{"group_id": "x", "description": "one"})
	db := &fakeDB{rows: map[string]Row{}, applied: true}
	_, err := execWith(db, []Operation{op}, Options{NonInteractive: true})
	if err != nil || db.casCalls != 1 {
		t.Fatalf("insert failed: %v", err)
	}
}
func TestMirrorRepair(t *testing.T) {
	op := makeOp("group_members", "upsert", Row{"group_id": "g", "user_id": "a", "user_type": "Human"})
	gm, _ := membershipRows(op)
	db := &fakeDB{rows: map[string]Row{fakeKey(tables["group_members"], gm): gm}, applied: true}
	out, err := execWith(db, []Operation{op}, Options{DryRun: true})
	if err != nil || len(db.statements) != 0 || !strings.Contains(out, "inconsistent mirror") {
		t.Fatalf("dry-run=%s err=%v", out, err)
	}
	_, err = execWith(db, []Operation{op}, Options{Yes: true})
	if err != nil || len(db.statements) != 1 || len(db.statements[0]) != 2 {
		t.Fatalf("mirroring failed: %v", err)
	}
}
func TestDuplicateMembership(t *testing.T) {
	row := Row{"user_id": "a", "user_type": "SDK", "group_id": "g"}
	op := []Operation{makeOp("group_members", "upsert", row), makeOp("user_groups", "delete", row)}
	_, err := execWith(&fakeDB{}, op, Options{})
	if err == nil || !strings.Contains(err.Error(), "duplicate logical PK") {
		t.Fatalf("expected conflict: %v", err)
	}
}
func TestUnknownFieldRejected(t *testing.T) {
	path := filepath.Join(t.TempDir(), "input.json")
	data := []byte(`{"operations":[{"table":"groups","action":"upsert","data":{"group_id":"g","oops":"bad"}}]}`)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadInput(path); err == nil || !strings.Contains(err.Error(), "unknown column") {
		t.Fatalf("wanted validation error: %v", err)
	}
}
