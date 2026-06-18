// Package replay reads persisted realtime events for cursor-based catch-up on
// (re)subscribe. It is a port of realtime-service's EventReplayService over the
// realtime.workspace_event table.
package replay

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/protocol"
)

// ErrGapTooLarge means more than the replay limit of events were missed; the
// client must refetch a fresh snapshot instead of replaying.
var ErrGapTooLarge = errors.New("replay gap too large")

const (
	cursorSQL = `SELECT COALESCE(MAX(id), 0) FROM realtime.workspace_event WHERE topic = $1`
	sinceSQL  = `
SELECT id, event_type, schema_version, occurred_at, actor_user_id, payload
FROM realtime.workspace_event
WHERE topic = $1 AND id > $2 AND id <= $3
ORDER BY id ASC
LIMIT $4`
)

// Service answers replay queries against the shared database.
type Service struct {
	pool  *pgxpool.Pool
	limit int
}

// New returns a replay Service. limit caps how many missed events may be
// replayed before a gap is reported.
func New(pool *pgxpool.Pool, limit int) *Service {
	return &Service{pool: pool, limit: limit}
}

// CurrentCursor returns the highest persisted event id for a topic (0 if none).
func (s *Service) CurrentCursor(ctx context.Context, topic string) (int64, error) {
	var cursor int64
	if err := s.pool.QueryRow(ctx, cursorSQL, topic).Scan(&cursor); err != nil {
		return 0, fmt.Errorf("current cursor: %w", err)
	}
	return cursor, nil
}

// EventsSince returns events in (after, upTo] for a topic, oldest first.
//
// A first-time subscriber (after == nil) has no baseline to reconstruct, so it
// gets no replay (live-only) — replaying the whole backlog would fan each
// historical event into a redundant query invalidation. Returns ErrGapTooLarge
// if more than the configured limit of events were missed.
func (s *Service) EventsSince(ctx context.Context, topic string, after *int64, upTo int64) ([]protocol.Envelope, error) {
	if after == nil {
		return nil, nil
	}

	rows, err := s.pool.Query(ctx, sinceSQL, topic, *after, upTo, s.limit+1)
	if err != nil {
		return nil, fmt.Errorf("events since: %w", err)
	}
	defer rows.Close()

	events := make([]protocol.Envelope, 0, s.limit)
	for rows.Next() {
		var (
			env     protocol.Envelope
			payload []byte
		)
		if err := rows.Scan(
			&env.EventID,
			&env.EventType,
			&env.SchemaVersion,
			&env.OccurredAt,
			&env.ActorUserID,
			&payload,
		); err != nil {
			return nil, fmt.Errorf("scan event: %w", err)
		}
		if len(payload) > 0 {
			if err := json.Unmarshal(payload, &env.Data); err != nil {
				return nil, fmt.Errorf("decode event payload: %w", err)
			}
		}
		events = append(events, env)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate events: %w", err)
	}

	if len(events) > s.limit {
		return nil, ErrGapTooLarge
	}
	return events, nil
}
