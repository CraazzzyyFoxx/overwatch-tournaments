// Package safego runs background goroutines with panic recovery.
//
// net/http recovers panics on the per-request goroutine, and the sentryhttp
// middleware recovers the handler chain, but neither covers goroutines started
// explicitly with `go ...`. An unrecovered panic in such a goroutine terminates
// the ENTIRE process, taking down every connection — a full denial of service.
// Every self-launched goroutine in the gateway must therefore go through Go (or
// defer Recover) so a single edge-case panic is logged + reported instead of
// crashing the binary.
package safego

import (
	"fmt"
	"log/slog"
	"runtime/debug"

	"github.com/getsentry/sentry-go"
)

// Go runs fn in a new goroutine, recovering from any panic. The panic is logged
// at error level (via slog.Default) and reported to Sentry (a no-op when Sentry
// is disabled), then swallowed so the process keeps running.
func Go(fn func()) {
	go func() {
		defer Recover()
		fn()
	}()
}

// Recover is the deferred recovery used by Go. It is exported for goroutines that
// must manage their own lifecycle and only need the recovery: `defer safego.Recover()`.
func Recover() {
	r := recover()
	if r == nil {
		return
	}
	err, ok := r.(error)
	if !ok {
		err = fmt.Errorf("panic: %v", r)
	}
	slog.Default().Error("recovered panic in background goroutine",
		"panic", r,
		"stack", string(debug.Stack()),
	)
	sentry.CaptureException(err)
}
