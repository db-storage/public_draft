package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"
)

func main() {
	file := flag.String("f", "", "path to input JSON")
	hosts := flag.String("hosts", env("CASSANDRA_HOSTS", "127.0.0.1"), "comma-separated Cassandra hosts")
	port := flag.Int("port", envInt("CASSANDRA_PORT", 9042), "Cassandra native protocol port")
	user := flag.String("user", os.Getenv("CASSANDRA_USER"), "username (or CASSANDRA_USER)")
	dry := flag.Bool("dry-run", false, "query and print changes without writing")
	yes := flag.Bool("yes", false, "approve updates/deletes and mirror repairs")
	nonInteractive := flag.Bool("non-interactive", false, "fail if confirmation is required")
	flag.Parse()
	if *file == "" {
		fmt.Fprintln(os.Stderr, "-f is required")
		flag.Usage()
		os.Exit(2)
	}
	if *yes && *nonInteractive { /* --yes explicitly authorizes writes in CI */
	}
	input, err := loadInput(*file)
	if err != nil {
		fatal(err)
	}
	store, err := openStore(*hosts, *user, os.Getenv("CASSANDRA_PASSWORD"), *port)
	if err != nil {
		fatal(err)
	}
	defer store.Close()
	exec := NewExecutor(store, Options{DryRun: *dry, Yes: *yes, NonInteractive: *nonInteractive, Reader: os.Stdin, Writer: os.Stdout})
	if err := exec.Run(input.Operations); err != nil {
		fatal(err)
	}
	fmt.Println("\nCompleted.")
}
func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
func envInt(key string, def int) int {
	if n, e := strconv.Atoi(os.Getenv(key)); e == nil && n > 0 {
		return n
	}
	return def
}
func fatal(err error) { fmt.Fprintln(os.Stderr, "ERROR:", err); os.Exit(1) }
