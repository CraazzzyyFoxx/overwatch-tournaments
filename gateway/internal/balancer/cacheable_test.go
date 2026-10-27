package balancer

import (
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"
)

// viewerEcho stands in for edge.Dispatcher: every route answers with a call
// counter and the Authorization header it was handed.
type viewerEcho struct{ calls *atomic.Int64 }

func (b viewerEcho) Handler(edge.RouteSpec) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, _ = fmt.Fprintf(w, `{"n":%d,"viewer":%q}`, b.calls.Add(1), r.Header.Get("Authorization"))
	}
}

// The chat history carries a bearer's own role, can_write and mutes: wired as
// main.go wires it, a signed-in request is never served the cached anonymous
// envelope and never fills an entry, while the AuthNone board is shared with
// captains.
func TestDraftChatCacheIsAnonymousOnly(t *testing.T) {
	var calls atomic.Int64
	mux := http.NewServeMux()
	c := respcache.New(time.Minute, slog.New(slog.NewTextHandler(io.Discard, nil)))
	respcache.RegisterCached(mux, viewerEcho{&calls}, DraftReadRoutes, DraftCacheableReads, c)
	respcache.RegisterCached(mux, viewerEcho{&calls}, DraftRoutes, DraftCacheableReads, c)
	get := func(target, auth string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, target, nil)
		if auth != "" {
			req.Header.Set("Authorization", auth)
		}
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		return rec
	}

	const chat = "/api/v1/balancer/draft/sessions/5/chat?limit=50"
	anon := get(chat, "").Body.String()
	if rec := get(chat, "Bearer tok"); rec.Header().Get("X-Cache") != "" || rec.Body.String() == anon {
		t.Fatalf("bearer chat read was served from the cache: %s (X-Cache %q)", rec.Body.String(), rec.Header().Get("X-Cache"))
	}
	if rec := get(chat, ""); rec.Header().Get("X-Cache") != "HIT" || rec.Body.String() != anon {
		t.Fatalf("bearer chat read replaced the anonymous entry: %s", rec.Body.String())
	}
	const cold = "/api/v1/balancer/draft/sessions/5/chat?after_id=9"
	get(cold, "Bearer tok")
	if rec := get(cold, ""); rec.Header().Get("X-Cache") != "MISS" {
		t.Fatalf("bearer chat read filled the cache (X-Cache %q)", rec.Header().Get("X-Cache"))
	}

	const board = "/api/v1/balancer/draft/sessions/5/board"
	get(board, "")
	if rec := get(board, "Bearer tok"); rec.Header().Get("X-Cache") != "HIT" {
		t.Fatalf("a captain must share the viewer-agnostic board entry (X-Cache %q)", rec.Header().Get("X-Cache"))
	}
}
