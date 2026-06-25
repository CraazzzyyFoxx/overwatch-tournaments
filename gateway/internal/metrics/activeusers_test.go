package metrics

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func newTestRecorder(t *testing.T, now time.Time) *Recorder {
	t.Helper()
	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("miniredis: %v", err)
	}
	t.Cleanup(mr.Close)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	rec := NewRecorder(rdb, slog.New(slog.NewTextHandler(io.Discard, nil)))
	rec.now = func() time.Time { return now }
	return rec
}

func TestRecorderDayKey(t *testing.T) {
	rec := newTestRecorder(t, time.Date(2026, 6, 20, 15, 4, 5, 0, time.UTC))
	if got := rec.dayKey(rec.now()); got != "gateway:active:day:20260620" {
		t.Fatalf("dayKey = %q, want gateway:active:day:20260620", got)
	}
}

func TestRecorderCountsRollingWindows(t *testing.T) {
	now := time.Date(2026, 6, 20, 12, 0, 0, 0, time.UTC)
	rec := newTestRecorder(t, now)
	ctx := context.Background()

	add := func(daysAgo int, ids ...any) {
		key := rec.dayKey(now.AddDate(0, 0, -daysAgo))
		if err := rec.rdb.PFAdd(ctx, key, ids...).Err(); err != nil {
			t.Fatalf("PFAdd: %v", err)
		}
	}
	add(0, int64(1), int64(2), int64(3)) // today
	add(1, int64(3), int64(4))           // yesterday (3 overlaps)
	add(8, int64(5))                     // inside 30d window, outside 7d

	dau, wau, mau, err := rec.Counts(ctx)
	if err != nil {
		t.Fatalf("Counts: %v", err)
	}
	// DAU is a single-key PFCOUNT (exact). WAU/MAU are multi-key unions, which
	// HyperLogLog estimates — allow ±1 for tiny cardinalities.
	if dau != 3 {
		t.Errorf("DAU = %d, want 3", dau)
	}
	if !approx(wau, 4, 1) { // {1,2,3,4}
		t.Errorf("WAU = %d, want ~4", wau)
	}
	if !approx(mau, 5, 1) { // {1,2,3,4,5}
		t.Errorf("MAU = %d, want ~5", mau)
	}
	if !(dau <= wau && wau <= mau) {
		t.Errorf("windows not monotonic: dau=%d wau=%d mau=%d", dau, wau, mau)
	}
}

func approx(got, want, tol int64) bool {
	d := got - want
	if d < 0 {
		d = -d
	}
	return d <= tol
}

func TestRecorderRecordNeverBlocks(t *testing.T) {
	rec := newTestRecorder(t, time.Date(2026, 6, 20, 12, 0, 0, 0, time.UTC))
	// Far exceed the buffer with no consumer running: Record must not block.
	done := make(chan struct{})
	go func() {
		for i := range recordBuffer + 500 {
			rec.Record(int64(i))
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Record blocked when the buffer was full")
	}
}

func TestRecorderRunFlushesToRedis(t *testing.T) {
	now := time.Date(2026, 6, 20, 12, 0, 0, 0, time.UTC)
	rec := newTestRecorder(t, now)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go rec.Run(ctx)

	rec.Record(10)
	rec.Record(11)
	rec.Record(10) // duplicate

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if dau, _, _, err := rec.Counts(ctx); err == nil && dau >= 2 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("Run did not flush buffered records to Redis within timeout")
}
