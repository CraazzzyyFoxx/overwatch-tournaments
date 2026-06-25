package protocol

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestParseClientOp_Valid(t *testing.T) {
	cases := []struct {
		name string
		raw  string
		op   string
	}{
		{"ping", `{"op":"ping"}`, "ping"},
		{"subscribe", `{"op":"subscribe","topic":"tournament:1:bracket"}`, "subscribe"},
		{"subscribe with cursor", `{"op":"subscribe","topic":"tournament:1:bracket","after_event_id":42}`, "subscribe"},
		{"unsubscribe", `{"op":"unsubscribe","topic":"tournament:1:bracket"}`, "unsubscribe"},
		{"publish", `{"op":"publish","topic":"tournament:1:balancer","event_type":"balancer.drag","data":{"x":1}}`, "publish"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			op, perr := ParseClientOp([]byte(c.raw))
			if perr != nil {
				t.Fatalf("unexpected error: %+v", perr)
			}
			if op.Op != c.op {
				t.Fatalf("op = %q, want %q", op.Op, c.op)
			}
		})
	}
}

func TestParseClientOp_Invalid(t *testing.T) {
	cases := []struct {
		name string
		raw  string
		code string
	}{
		{"not json", `{not json`, "invalid_json"},
		{"unknown op", `{"op":"frobnicate","topic":"t"}`, "invalid_frame"},
		{"subscribe missing topic", `{"op":"subscribe"}`, "invalid_frame"},
		{"negative cursor", `{"op":"subscribe","topic":"t","after_event_id":-1}`, "invalid_frame"},
		{"publish missing event_type", `{"op":"publish","topic":"t"}`, "invalid_frame"},
		{"topic too long", `{"op":"subscribe","topic":"` + strings.Repeat("x", 256) + `"}`, "invalid_frame"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, perr := ParseClientOp([]byte(c.raw))
			if perr == nil {
				t.Fatalf("expected error, got nil")
			}
			if perr.Code != c.code {
				t.Fatalf("code = %q, want %q", perr.Code, c.code)
			}
		})
	}
}

func TestParseClientOp_InvalidFrameCarriesTopic(t *testing.T) {
	_, perr := ParseClientOp([]byte(`{"op":"bad","topic":"tournament:7:bracket"}`))
	if perr == nil || perr.Topic == nil || *perr.Topic != "tournament:7:bracket" {
		t.Fatalf("expected topic on error, got %+v", perr)
	}
}

func TestPublishDataFieldLimit(t *testing.T) {
	fields := make([]string, 0, MaxPublishFields+1)
	for i := 0; i <= MaxPublishFields; i++ {
		fields = append(fields, `"k`+string(rune('a'+i%26))+itoa(i)+`":1`)
	}
	raw := `{"op":"publish","topic":"t","event_type":"balancer.drag","data":{` + strings.Join(fields, ",") + `}}`
	_, perr := ParseClientOp([]byte(raw))
	if perr == nil || perr.Code != "invalid_frame" {
		t.Fatalf("expected invalid_frame for >%d fields, got %+v", MaxPublishFields, perr)
	}
}

func TestServerFrames(t *testing.T) {
	t.Run("pong", func(t *testing.T) {
		assertJSONEq(t, PongFrame(), map[string]any{"op": "pong"})
	})
	t.Run("subscribed", func(t *testing.T) {
		assertJSONEq(t, SubscribedFrame("t", 12), map[string]any{"op": "subscribed", "topic": "t", "cursor": float64(12)})
	})
	t.Run("error with nil topic emits null", func(t *testing.T) {
		var m map[string]any
		if err := json.Unmarshal(ErrorFrame("forbidden", "no", nil), &m); err != nil {
			t.Fatal(err)
		}
		if v, ok := m["topic"]; !ok || v != nil {
			t.Fatalf("topic should be present and null, got %v (present=%v)", v, ok)
		}
	})
	t.Run("event", func(t *testing.T) {
		env := Envelope{
			EventID:       0,
			EventType:     "balancer.presence",
			SchemaVersion: 1,
			OccurredAt:    time.Unix(0, 0).UTC(),
			Data:          map[string]any{"user_ids": []any{}},
		}
		var m map[string]any
		if err := json.Unmarshal(EventFrame("tournament:1:balancer", env), &m); err != nil {
			t.Fatal(err)
		}
		if m["op"] != "event" || m["topic"] != "tournament:1:balancer" {
			t.Fatalf("bad event frame: %v", m)
		}
		ev := m["event"].(map[string]any)
		if ev["event_type"] != "balancer.presence" || ev["actor_user_id"] != nil {
			t.Fatalf("bad envelope: %v", ev)
		}
	})
}

func TestEventFrameTopic(t *testing.T) {
	topic, ok := EventFrameTopic([]byte(`{"op":"event","topic":"tournament:9:bracket","event":{}}`))
	if !ok || topic != "tournament:9:bracket" {
		t.Fatalf("topic=%q ok=%v", topic, ok)
	}
	if _, ok := EventFrameTopic([]byte(`{"op":"event"}`)); ok {
		t.Fatal("expected ok=false when topic missing")
	}
}

func assertJSONEq(t *testing.T, got []byte, want map[string]any) {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(got, &m); err != nil {
		t.Fatal(err)
	}
	for k, v := range want {
		if m[k] != v {
			t.Fatalf("key %q = %v, want %v (full: %v)", k, m[k], v, m)
		}
	}
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	var b []byte
	for i > 0 {
		b = append([]byte{byte('0' + i%10)}, b...)
		i /= 10
	}
	return string(b)
}
