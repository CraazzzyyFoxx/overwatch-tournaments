package rpc

import (
	"context"
	"strconv"
	"testing"
	"time"
)

func TestBuildPublishing_WithDeadline(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	deadline, _ := ctx.Deadline()

	pub := buildPublishing(ctx, "cid", "reply-q", []byte(`{"a":1}`))

	if pub.CorrelationId != "cid" || pub.ReplyTo != "reply-q" || string(pub.Body) != `{"a":1}` {
		t.Fatalf("base fields lost: %+v", pub)
	}
	ms, err := strconv.ParseInt(pub.Expiration, 10, 64)
	if err != nil {
		t.Fatalf("expiration %q is not integer milliseconds: %v", pub.Expiration, err)
	}
	if ms <= 0 || ms > 30_000 {
		t.Fatalf("expiration %dms outside (0, 30000]", ms)
	}
	got, ok := pub.Headers[deadlineHeader].(int64)
	if !ok || got != deadline.UnixMilli() {
		t.Fatalf("%s = %v, want %d", deadlineHeader, pub.Headers[deadlineHeader], deadline.UnixMilli())
	}
}

func TestBuildPublishing_NoDeadline(t *testing.T) {
	pub := buildPublishing(context.Background(), "cid", "reply-q", nil)
	if pub.Expiration != "" {
		t.Fatalf("no-deadline publish must not set TTL, got %q", pub.Expiration)
	}
	if pub.Headers != nil {
		t.Fatalf("no-deadline publish must not set headers, got %v", pub.Headers)
	}
}

func TestBuildPublishing_ExpiredContextStillPositiveTTL(t *testing.T) {
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	pub := buildPublishing(ctx, "cid", "reply-q", nil)
	if pub.Expiration != "1" {
		t.Fatalf("already-expired deadline must clamp TTL to 1ms (broker drops ASAP), got %q", pub.Expiration)
	}
}
