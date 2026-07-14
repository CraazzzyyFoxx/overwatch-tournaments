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
// is applied as a server-side backstop that cancels any query running longer,
// so a slow/hung Postgres can't pin pool connections against the gateway's
// unauthenticated /ws ACL/replay lookups.
//
// When pgBouncer is true (transaction pooling), prepared statements are
// disabled by switching to the simple query protocol — otherwise pgBouncer
// silently breaks pgx's server-side prepared statements.
func Connect(ctx context.Context, url string, pgBouncer bool, maxConns int, statementTimeout time.Duration) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	if maxConns > 0 {
		cfg.MaxConns = int32(maxConns)
	}
	cfg.MaxConnIdleTime = 5 * time.Minute
	// Sent as a startup parameter. Under pgBouncer transaction pooling it must be
	// allowed via ignore_startup_parameters (or set on the Postgres role instead).
	if statementTimeout > 0 {
		if cfg.ConnConfig.RuntimeParams == nil {
			cfg.ConnConfig.RuntimeParams = map[string]string{}
		}
		cfg.ConnConfig.RuntimeParams["statement_timeout"] = strconv.FormatInt(statementTimeout.Milliseconds(), 10)
	}
	if pgBouncer {
		cfg.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeSimpleProtocol
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
