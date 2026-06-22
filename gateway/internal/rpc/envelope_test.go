package rpc

import (
	"encoding/json"
	"testing"
)

func TestStatusForCode(t *testing.T) {
	cases := map[string]int{
		"bad_request":  400,
		"unauthorized": 401,
		"forbidden":    403,
		"not_found":    404,
		"conflict":     409,
		"internal":     500,
		"weird":        500,
	}
	for code, want := range cases {
		if got := StatusForCode(code); got != want {
			t.Errorf("StatusForCode(%q) = %d, want %d", code, got, want)
		}
	}
}

func TestEnvelopeUnmarshal(t *testing.T) {
	t.Run("ok", func(t *testing.T) {
		var e Envelope
		if err := json.Unmarshal([]byte(`{"ok":true,"data":{"sub":42}}`), &e); err != nil {
			t.Fatal(err)
		}
		if !e.OK || e.Error != nil || string(e.Data) != `{"sub":42}` {
			t.Fatalf("unexpected: %+v", e)
		}
	})
	t.Run("error", func(t *testing.T) {
		var e Envelope
		if err := json.Unmarshal([]byte(`{"ok":false,"error":{"code":"unauthorized","message":"no"}}`), &e); err != nil {
			t.Fatal(err)
		}
		if e.OK || e.Error == nil || e.Error.Code != "unauthorized" {
			t.Fatalf("unexpected: %+v", e)
		}
	})
}
