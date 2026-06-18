package rpc

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestRPCInterop is the Go<->FastStream interop spike. It requires:
//   - RabbitMQ on GATEWAY_RPC_URL (default amqp://guest:guest@localhost:5672)
//   - the FastStream responder running (scripts/rpc-spike/responder.py)
//
// Run: GATEWAY_RPC_SPIKE=1 go test ./internal/rpc/ -run TestRPCInterop -v
func TestRPCInterop(t *testing.T) {
	if os.Getenv("GATEWAY_RPC_SPIKE") == "" {
		t.Skip("set GATEWAY_RPC_SPIKE=1 (and run the FastStream responder) to run the interop spike")
	}
	url := os.Getenv("GATEWAY_RPC_URL")
	if url == "" {
		url = "amqp://guest:guest@localhost:5672"
	}

	c, err := Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := c.Call(ctx, "rpc.spike.echo", []byte(`{"hello":"world","n":42}`))
	if err != nil {
		t.Fatalf("rpc call: %v", err)
	}

	var got map[string]any
	if err := json.Unmarshal(resp, &got); err != nil {
		t.Fatalf("unmarshal reply %q: %v", resp, err)
	}
	t.Logf("reply: %s", resp)

	if got["pong"] != true || got["service"] != "faststream" {
		t.Fatalf("unexpected reply: %v", got)
	}
	echo, ok := got["echo"].(map[string]any)
	if !ok || echo["hello"] != "world" || echo["n"] != float64(42) {
		t.Fatalf("echo mismatch: %v", got["echo"])
	}
}

// TestIdentityValidateToken_Garbage hits the real identity-svc validate_token
// RPC method with an invalid token and asserts the error envelope. Requires the
// identity-svc worker running. Run:
//
//	GATEWAY_RPC_SPIKE=1 go test ./internal/rpc/ -run TestIdentityValidateToken -v
func TestIdentityValidateToken_Garbage(t *testing.T) {
	if os.Getenv("GATEWAY_RPC_SPIKE") == "" {
		t.Skip("set GATEWAY_RPC_SPIKE=1 (and run identity-svc) to run")
	}
	url := os.Getenv("GATEWAY_RPC_URL")
	if url == "" {
		url = "amqp://guest:guest@localhost:5672"
	}

	c, err := Dial(url)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer c.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := c.Call(ctx, "rpc.identity.validate_token", []byte(`{"token":"garbage.jwt.token"}`))
	if err != nil {
		t.Fatalf("rpc call: %v", err)
	}
	t.Logf("envelope: %s", resp)

	var env struct {
		OK    bool `json:"ok"`
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(resp, &env); err != nil {
		t.Fatalf("unmarshal envelope %q: %v", resp, err)
	}
	if env.OK || env.Error.Code != "unauthorized" {
		t.Fatalf("expected ok=false code=unauthorized, got %+v", env)
	}
}
