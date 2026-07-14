package rpc

import (
	"errors"
	"fmt"
	"testing"
)

func TestIsUnavailable(t *testing.T) {
	cases := []struct {
		err  error
		want bool
	}{
		{ErrNotConnected, true},
		{ErrDisconnected, true},
		{ErrOverloaded, true},
		{fmt.Errorf("rpc to %q: %w", "q", ErrOverloaded), true},
		{errors.New("boom"), false},
		{nil, false},
	}
	for _, c := range cases {
		if got := IsUnavailable(c.err); got != c.want {
			t.Fatalf("IsUnavailable(%v) = %v, want %v", c.err, got, c.want)
		}
	}
}

func TestNew_OptionsApply(t *testing.T) {
	shed := []string{}
	c := New("amqp://invalid-host-never-connects:5672", nil,
		WithMaxInFlight(5),
		WithShedHook(func(q string) { shed = append(shed, q) }),
	)
	defer func() { _ = c.Close() }()
	if c.limiter == nil || c.limiter.max != 5 {
		t.Fatalf("WithMaxInFlight not applied: %+v", c.limiter)
	}
	if c.onShed == nil {
		t.Fatal("WithShedHook not applied")
	}
	c.onShed("q1")
	if len(shed) != 1 || shed[0] != "q1" {
		t.Fatalf("shed hook broken: %v", shed)
	}
}
