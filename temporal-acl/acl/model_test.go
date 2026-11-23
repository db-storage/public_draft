package acl

import (
	"context"
	"errors"
	"reflect"
	"testing"
)

type fakeRepo struct {
	exists  bool
	direct  []Grant
	groups  []string
	grouped map[string][]Grant
	err     error
}

func (f *fakeRepo) UserExists(context.Context, Identity) (bool, error) { return f.exists, f.err }
func (f *fakeRepo) DirectPermissions(context.Context, Identity) ([]Grant, error) {
	return f.direct, f.err
}
func (f *fakeRepo) UserGroups(context.Context, Identity) ([]string, error) { return f.groups, f.err }
func (f *fakeRepo) GroupPermissions(_ context.Context, g string) ([]Grant, error) {
	return f.grouped[g], f.err
}
func (f *fakeRepo) Close() error { return nil }
func TestMergeDirectAndInherited(t *testing.T) {
	f := &fakeRepo{exists: true, direct: []Grant{{"ns1", "read"}}, groups: []string{"g1", "g2"}, grouped: map[string][]Grant{
		"g1": {{"ns1", "write"}, {"ns2", "worker"}}, "g2": {{"ns1", "admin"}},
	}}
	got, err := newModel(f, 10).GetPermissions(context.Background(), Identity{"bob", "Human"})
	want := Permissions{"ns1": RoleReader | RoleWriter | RoleAdmin, "ns2": RoleWorker}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("got=%v err=%v want=%v", got, err, want)
	}
}
func TestAbsentUser(t *testing.T) {
	got, err := newModel(&fakeRepo{}, 10).GetPermissions(context.Background(), Identity{"bob", "Human"})
	if err != nil || len(got) != 0 {
		t.Fatalf("got=%v err=%v", got, err)
	}
}
func TestDBErrorFailsClosed(t *testing.T) {
	_, err := newModel(&fakeRepo{err: errors.New("db down")}, 10).GetPermissions(context.Background(), Identity{"bob", "Human"})
	if err == nil {
		t.Fatal("db failure must be an error")
	}
}
func TestInvalidGrantFailsClosed(t *testing.T) {
	_, err := newModel(&fakeRepo{exists: true, direct: []Grant{{"ns", "owner"}}}, 10).GetPermissions(context.Background(), Identity{"bob", "Human"})
	if err == nil {
		t.Fatal("unrecognized role must be an error")
	}
}
func TestGroupLimit(t *testing.T) {
	_, err := newModel(&fakeRepo{exists: true, groups: []string{"a", "b"}}, 1).GetPermissions(context.Background(), Identity{"bob", "Human"})
	if err == nil {
		t.Fatal("expected max groups error")
	}
}
func TestUnknownUserType(t *testing.T) {
	_, err := newModel(&fakeRepo{}, 10).GetPermissions(context.Background(), Identity{"bob", "root"})
	if !errors.Is(err, ErrInvalidIdentity) {
		t.Fatal(err)
	}
}
