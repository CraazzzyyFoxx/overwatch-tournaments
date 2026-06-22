package metrics

import (
	"context"
	"time"
)

// ConnCounter reports live WebSocket connection stats. *ws.Hub satisfies it.
type ConnCounter interface {
	Count() int
	DistinctUsers() int
}

// CountsProvider supplies the rolling unique-active-user windows. *Recorder
// satisfies it.
type CountsProvider interface {
	Counts(ctx context.Context) (dau, wau, mau int64, err error)
}

// Sampler periodically refreshes the gauge metrics that cannot be updated
// inline: live WebSocket connections and the rolling active-user windows. It
// blocks until ctx is cancelled, so run it in a goroutine. rec or hub may be nil.
func (m *Metrics) Sampler(ctx context.Context, rec CountsProvider, hub ConnCounter, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	sample := func() {
		if hub != nil {
			m.wsConns.WithLabelValues("total").Set(float64(hub.Count()))
			m.wsConns.WithLabelValues("authenticated").Set(float64(hub.DistinctUsers()))
		}
		if rec != nil {
			cctx, cancel := context.WithTimeout(ctx, 5*time.Second)
			dau, wau, mau, err := rec.Counts(cctx)
			cancel()
			if err == nil {
				m.activeUsers.WithLabelValues("1d").Set(float64(dau))
				m.activeUsers.WithLabelValues("7d").Set(float64(wau))
				m.activeUsers.WithLabelValues("30d").Set(float64(mau))
			}
		}
	}

	sample()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			sample()
		}
	}
}
