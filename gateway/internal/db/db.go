// Package db opens the shared Postgres connection pool used for read-only
// queries (event replay, ACL membership lookups).
package db

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Connect opens and verifies a pgx connection pool against the given URL.
//
// maxConns caps the pool (<=0 keeps pgx's default). statementTimeout, when > 0,
// is applied (direct Postgres only) as a server-side backstop that cancels any
// query running longer, so a slow/hung Postgres can't pin pool connections
// against the gateway's unauthenticated /ws ACL/replay lookups. It is skipped
// under pgBouncer, which rejects it as an unsupported startup parameter.
//
// When pgBouncer is true (transaction pooling), prepared statements are
// disabled by switching to the simple query protocol — otherwise pgBouncer
// silently breaks pgx's server-side prepared statements.
func Connect(ctx context.Context, url string, pgBouncer bool, maxConns int, statementTimeout time.Duration) (*pgxpool.Pool, error) {
	cfg, err := buildPoolConfig(url, pgBouncer, maxConns, statementTimeout)
	if err != nil {
		return nil, err
	}

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("connect database: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}
	return pool, nil
}

// buildPoolConfig assembles the pgxpool config (extracted from Connect so the
// pgBouncer-sensitive branches are unit-testable without a live database).
func buildPoolConfig(url string, pgBouncer bool, maxConns int, statementTimeout time.Duration) (*pgxpool.Config, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	if maxConns > 0 {
		cfg.MaxConns = int32(maxConns)
	}
	cfg.MaxConnIdleTime = 5 * time.Minute
	// statement_timeout is sent as a libpq startup parameter, which pgBouncer
	// rejects by default ("unsupported startup parameter") and crashes the
	// connection — so only send it on a DIRECT Postgres connection. Under
	// pgBouncer, set the timeout on the Postgres role instead
	// (ALTER ROLE ... SET statement_timeout). Either way the gateway's
	// per-request context deadlines already bound query time.
	if statementTimeout > 0 && !pgBouncer {
		if cfg.ConnConfig.RuntimeParams == nil {
			cfg.ConnConfig.RuntimeParams = map[string]string{}
		}
		cfg.ConnConfig.RuntimeParams["statement_timeout"] = strconv.FormatInt(statementTimeout.Milliseconds(), 10)
	}
	if pgBouncer {
		cfg.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeSimpleProtocol
	}
	return cfg, nil
}
