package db

import (
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// Regression: sending statement_timeout as a startup parameter crashes the
// gateway against pgBouncer ("unsupported startup parameter"). It must be
// skipped when pgBouncer is enabled.
func TestBuildPoolConfig_StatementTimeoutSkippedUnderPgBouncer(t *testing.T) {
	cfg, err := buildPoolConfig("postgres://u:p@localhost:6432/db", true, 16, 15*time.Second)
	if err != nil {
		t.Fatalf("buildPoolConfig: %v", err)
	}
	if _, ok := cfg.ConnConfig.RuntimeParams["statement_timeout"]; ok {
		t.Fatal("statement_timeout must NOT be a startup param under pgBouncer")
	}
	if cfg.ConnConfig.DefaultQueryExecMode != pgx.QueryExecModeSimpleProtocol {
		t.Fatal("pgBouncer mode must use the simple query protocol")
	}
}

func TestBuildPoolConfig_StatementTimeoutOnDirectPostgres(t *testing.T) {
	cfg, err := buildPoolConfig("postgres://u:p@localhost:5432/db", false, 16, 15*time.Second)
	if err != nil {
		t.Fatalf("buildPoolConfig: %v", err)
	}
	if got := cfg.ConnConfig.RuntimeParams["statement_timeout"]; got != "15000" {
		t.Fatalf("statement_timeout = %q, want 15000", got)
	}
	if cfg.MaxConns != 16 {
		t.Fatalf("MaxConns = %d, want 16", cfg.MaxConns)
	}
}

func TestBuildPoolConfig_ZeroTimeoutOmitsParam(t *testing.T) {
	cfg, err := buildPoolConfig("postgres://u:p@localhost:5432/db", false, 0, 0)
	if err != nil {
		t.Fatalf("buildPoolConfig: %v", err)
	}
	if _, ok := cfg.ConnConfig.RuntimeParams["statement_timeout"]; ok {
		t.Fatal("statement_timeout must be omitted when 0")
	}
}
