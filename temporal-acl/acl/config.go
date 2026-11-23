package acl

import (
	"encoding/json"
	"fmt"
	"os"
)

type Config struct {
	Enabled   bool            `json:"enabled"`
	Provider  string          `json:"provider"` // cassandra | static
	Cassandra CassandraConfig `json:"cassandra"`
}

func ReadConfig(path string) (Config, error) {
	var c Config
	b, err := os.ReadFile(path)
	if err != nil {
		return c, err
	}
	err = json.Unmarshal(b, &c)
	return c, err
}

// Disabled = not installed; the caller must retain a separately secured mapper/authorizer.
func NewFromConfig(c Config) (PermissionModel, error) {
	if !c.Enabled {
		return nil, fmt.Errorf("ACL disabled: do not silently disable authorization")
	}
	switch c.Provider {
	case "cassandra":
		return NewCassandraModel(c.Cassandra)
	default:
		return nil, fmt.Errorf("unsupported ACL provider %q (static is test-only)", c.Provider)
	}
}
