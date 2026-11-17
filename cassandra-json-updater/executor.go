package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
	"time"
)

type Change struct {
	Column   string
	Old, New any
}
type Options struct {
	DryRun, Yes, NonInteractive bool
	Reader                      io.Reader
	Writer                      io.Writer
}
type Executor struct {
	db    Store
	opt   Options
	input *bufio.Reader
}

func NewExecutor(db Store, opt Options) *Executor {
	if opt.Reader == nil {
		opt.Reader = strings.NewReader("")
	}
	if opt.Writer == nil {
		opt.Writer = io.Discard
	}
	return &Executor{db: db, opt: opt, input: bufio.NewReader(opt.Reader)}
}
func pretty(v any) string {
	if v == nil {
		return "NULL"
	}
	if t, ok := v.(time.Time); ok {
		return t.UTC().Format(time.RFC3339Nano)
	}
	return fmt.Sprint(v)
}
func diff(old Row, incoming Row, t Table) []Change {
	cols := make([]string, 0, len(incoming))
	for c := range incoming {
		if !keyColumns(t)[c] {
			cols = append(cols, c)
		}
	}
	sort.Strings(cols)
	out := []Change{}
	for _, c := range cols {
		if !sameValue(old[c], incoming[c]) {
			out = append(out, Change{c, old[c], incoming[c]})
		}
	}
	return out
}
func (e *Executor) printDiff(changes []Change) {
	fmt.Fprintln(e.opt.Writer, "  FIELD                 OLD                          NEW")
	for _, ch := range changes {
		fmt.Fprintf(e.opt.Writer, "  %-21s %-28s %s\n", ch.Column, pretty(ch.Old), pretty(ch.New))
	}
}
func (e *Executor) confirm(message string) (bool, error) {
	if e.opt.DryRun {
		return false, nil
	}
	if e.opt.Yes {
		return true, nil
	}
	if e.opt.NonInteractive {
		return false, fmt.Errorf("confirmation required in --non-interactive mode (use --yes after review)")
	}
	fmt.Fprintf(e.opt.Writer, "%s [y/N]: ", message)
	s, err := e.input.ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return false, err
	}
	s = strings.ToLower(strings.TrimSpace(s))
	return s == "y" || s == "yes", nil
}
func (e *Executor) Run(operations []Operation) error {
	// Avoid conflicting instructions for the same logical row in one file.
	seen := map[string]bool{}
	for i, op := range operations {
		id := op.Table
		if op.Table == "user_groups" || op.Table == "group_members" {
			id = "membership"
		}
		vals := []string{}
		if id == "membership" {
			for _, k := range []string{"user_id", "user_type", "group_id"} {
				vals = append(vals, pretty(op.Row[k]))
			}
		} else {
			for _, k := range tables[op.Table].PK {
				vals = append(vals, pretty(op.Row[k]))
			}
		}
		id += "|" + strings.Join(vals, "\x00")
		if seen[id] {
			return fmt.Errorf("operation %d: duplicate logical PK in input: %s", i+1, id)
		}
		seen[id] = true
	}
	for i, op := range operations {
		fmt.Fprintf(e.opt.Writer, "\n[%d/%d] %s %s\n", i+1, len(operations), strings.ToUpper(op.Action), op.Table)
		var err error
		if op.Table == "user_groups" || op.Table == "group_members" {
			err = e.membership(op)
		} else {
			err = e.normal(op)
		}
		if err != nil {
			return fmt.Errorf("operation %d (%s): %w", i+1, op.Table, err)
		}
	}
	return nil
}
func (e *Executor) normal(op Operation) error {
	t := tables[op.Table]
	old, exists, err := e.db.Get(t, op.Row)
	if err != nil {
		return err
	}
	if op.Action == "delete" {
		if !exists {
			fmt.Fprintln(e.opt.Writer, "  SKIP: not found")
			return nil
		}
		fmt.Fprintln(e.opt.Writer, "  Existing record:")
		e.printDiff(diff(old, nullifyNonPK(old, t), t))
		if e.opt.DryRun {
			fmt.Fprintln(e.opt.Writer, "  DRY-RUN: DELETE")
			return nil
		}
		yes, err := e.confirm("  Delete existing record?")
		if err != nil {
			return err
		}
		if !yes {
			fmt.Fprintln(e.opt.Writer, "  SKIP")
			return nil
		}
		applied, err := e.db.CAS(deleteCASStmt(t, op.Row, old))
		if err != nil {
			return err
		}
		if !applied {
			return fmt.Errorf("concurrent modification detected, delete not applied")
		}
		fmt.Fprintln(e.opt.Writer, "  DELETED")
		return nil
	}
	if !exists {
		fmt.Fprintln(e.opt.Writer, "  INSERT (PK not found)")
		if e.opt.DryRun {
			fmt.Fprintln(e.opt.Writer, "  DRY-RUN: no write")
			return nil
		}
		applied, err := e.db.CAS(insertStmt(t, op.Row, true))
		if err != nil {
			return err
		}
		if !applied {
			return fmt.Errorf("concurrent insertion detected, insert not applied")
		}
		fmt.Fprintln(e.opt.Writer, "  INSERTED")
		return nil
	}
	changes := diff(old, op.Row, t)
	if len(changes) == 0 {
		fmt.Fprintln(e.opt.Writer, "  SKIP: supplied fields unchanged")
		return nil
	}
	e.printDiff(changes)
	if e.opt.DryRun {
		fmt.Fprintln(e.opt.Writer, "  DRY-RUN: UPDATE")
		return nil
	}
	yes, err := e.confirm("  Update existing record?")
	if err != nil {
		return err
	}
	if !yes {
		fmt.Fprintln(e.opt.Writer, "  SKIP")
		return nil
	}
	applied, err := e.db.CAS(updateCASStmt(t, old, op.Row, changes))
	if err != nil {
		return err
	}
	if !applied {
		return fmt.Errorf("concurrent modification detected, update not applied")
	}
	fmt.Fprintln(e.opt.Writer, "  UPDATED")
	return nil
}
func nullifyNonPK(old Row, t Table) Row {
	m := Row{}
	for c := range old {
		if !keyColumns(t)[c] {
			m[c] = nil
		}
	}
	return m
}
func membershipRows(op Operation) (Row, Row) {
	gm := Row{"group_id": op.Row["group_id"], "user_type": op.Row["user_type"], "user_id": op.Row["user_id"]}
	if v, ok := op.Row["added_at"]; ok {
		gm["added_at"] = v
	}
	ug := Row{"user_id": op.Row["user_id"], "user_type": op.Row["user_type"], "group_id": op.Row["group_id"]}
	return gm, ug
}
func (e *Executor) membership(op Operation) error {
	gm, ug := membershipRows(op)
	mt, ut := tables["group_members"], tables["user_groups"]
	oldM, mExists, err := e.db.Get(mt, gm)
	if err != nil {
		return err
	}
	_, uExists, err := e.db.Get(ut, ug)
	if err != nil {
		return err
	}
	if mExists != uExists {
		fmt.Fprintf(e.opt.Writer, "  WARNING: inconsistent mirror: group_members=%v, user_groups=%v\n", mExists, uExists)
	}
	if op.Action == "delete" {
		if !mExists && !uExists {
			fmt.Fprintln(e.opt.Writer, "  SKIP: neither exists")
			return nil
		}
		fmt.Fprintln(e.opt.Writer, "  DELETE both membership rows")
		if e.opt.DryRun {
			fmt.Fprintln(e.opt.Writer, "  DRY-RUN: no write")
			return nil
		}
		yes, err := e.confirm("  Delete membership from both tables?")
		if err != nil {
			return err
		}
		if !yes {
			fmt.Fprintln(e.opt.Writer, "  SKIP")
			return nil
		}
		// Logged batch is atomic but does NOT provide isolation or read->write CAS across partitions.
		if err := e.db.Execute([]Statement{deleteStmt(mt, gm), deleteStmt(ut, ug)}); err != nil {
			return err
		}
		fmt.Fprintln(e.opt.Writer, "  DELETED both")
		return nil
	}
	changes := []Change{}
	if mExists {
		changes = diff(oldM, gm, mt)
	}
	if mExists && uExists && len(changes) == 0 {
		fmt.Fprintln(e.opt.Writer, "  SKIP: both rows present, supplied fields unchanged")
		return nil
	}
	if len(changes) > 0 {
		e.printDiff(changes)
	}
	if !mExists {
		fmt.Fprintln(e.opt.Writer, "  group_members: missing -> insert")
	}
	if !uExists {
		fmt.Fprintln(e.opt.Writer, "  user_groups: missing -> insert")
	}
	if e.opt.DryRun {
		fmt.Fprintln(e.opt.Writer, "  DRY-RUN: logged batch for both tables")
		return nil
	}
	if mExists || uExists {
		yes, err := e.confirm("  Update/repair membership in both tables?")
		if err != nil {
			return err
		}
		if !yes {
			fmt.Fprintln(e.opt.Writer, "  SKIP")
			return nil
		}
	}
	// For existing group_members, preserve added_at unless supplied explicitly.
	if mExists {
		merged := Row{}
		for k, v := range oldM {
			merged[k] = v
		}
		for k, v := range gm {
			merged[k] = v
		}
		gm = merged
	}
	if err := e.db.Execute([]Statement{insertStmt(mt, gm, false), insertStmt(ut, ug, false)}); err != nil {
		return err
	}
	fmt.Fprintln(e.opt.Writer, "  UPSERTED both (LOGGED BATCH)")
	return nil
}
