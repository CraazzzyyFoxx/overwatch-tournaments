package metrics

import (
	"context"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	activeKeyPrefix = "gateway:active:day:"
	// activeKeyTTL keeps daily HyperLogLog keys long enough for the 30-day
	// rolling window plus slack, then lets Redis reclaim them.
	activeKeyTTL = 35 * 24 * time.Hour
	recordBuffer = 4096
	flushBatch   = 256
)

// Recorder counts unique active users in Redis HyperLogLog keys, one per UTC
// day. Writes are buffered and flushed by a single goroutine so the request
// path never blocks on Redis.
type Recorder struct {
	rdb *redis.Client
	ch  chan int64
	now func() time.Time
	log *slog.Logger
}

// NewRecorder builds a recorder over the given Redis client.
func NewRecorder(rdb *redis.Client, logger *slog.Logger) *Recorder {
	return &Recorder{
		rdb: rdb,
		ch:  make(chan int64, recordBuffer),
		now: time.Now,
		log: logger,
	}
}

// Record enqueues a user ID. It is non-blocking and drops the ID when the
// buffer is full (the counts are statistical, not exact).
func (r *Recorder) Record(userID int64) {
	select {
	case r.ch <- userID:
	default:
	}
}

// Run drains the buffer into the current day's HyperLogLog until ctx is
// cancelled. IDs are batched into a single PFADD to amortise round-trips. On
// cancellation it drains and flushes whatever is buffered (with a fresh
// context) so a restart does not silently drop the current batch.
func (r *Recorder) Run(ctx context.Context) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	batch := make([]any, 0, flushBatch)
	for {
		select {
		case <-ctx.Done():
			for drained := false; !drained; {
				select {
				case id := <-r.ch:
					batch = append(batch, id)
				default:
					drained = true
				}
			}
			flushCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			r.flush(flushCtx, batch)
			cancel()
			return
		case id := <-r.ch:
			batch = append(batch, id)
			if len(batch) >= flushBatch {
				r.flush(ctx, batch)
				batch = batch[:0]
			}
		case <-ticker.C:
			r.flush(ctx, batch)
			batch = batch[:0]
		}
	}
}

// flush writes the batch to the current day's HyperLogLog. It is a no-op for an
// empty batch. Redis errors are logged unless ctx was cancelled.
func (r *Recorder) flush(ctx context.Context, batch []any) {
	if len(batch) == 0 {
		return
	}
	key := r.dayKey(r.now())
	pipe := r.rdb.Pipeline()
	pipe.PFAdd(ctx, key, batch...)
	pipe.Expire(ctx, key, activeKeyTTL)
	if _, err := pipe.Exec(ctx); err != nil && ctx.Err() == nil {
		r.log.Warn("active-user flush failed", "err", err)
	}
}

func (r *Recorder) dayKey(t time.Time) string {
	return activeKeyPrefix + t.UTC().Format("20060102")
}

// dayKeys returns the keys for the last n UTC days (most recent first).
func (r *Recorder) dayKeys(n int) []string {
	now := r.now().UTC()
	keys := make([]string, n)
	for i := range n {
		keys[i] = r.dayKey(now.AddDate(0, 0, -i))
	}
	return keys
}

// Counts returns unique active users for the rolling 1/7/30-day windows. Each
// is a PFCOUNT over the union of the relevant daily keys (no merge key needed).
func (r *Recorder) Counts(ctx context.Context) (dau, wau, mau int64, err error) {
	if dau, err = r.rdb.PFCount(ctx, r.dayKeys(1)...).Result(); err != nil {
		return 0, 0, 0, err
	}
	if wau, err = r.rdb.PFCount(ctx, r.dayKeys(7)...).Result(); err != nil {
		return 0, 0, 0, err
	}
	if mau, err = r.rdb.PFCount(ctx, r.dayKeys(30)...).Result(); err != nil {
		return 0, 0, 0, err
	}
	return dau, wau, mau, nil
}
