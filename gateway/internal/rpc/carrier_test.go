package rpc

import (
	"slices"
	"testing"

	amqp "github.com/rabbitmq/amqp091-go"
)

func TestHeaderCarrierRoundTrip(t *testing.T) {
	tbl := amqp.Table{}
	c := headerCarrier(tbl)

	c.Set("traceparent", "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01")
	if got, want := c.Get("traceparent"), "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"; got != want {
		t.Errorf("Get(traceparent) = %q, want %q", got, want)
	}
	// The value must land in the underlying table as a string (what the
	// FastStream side reads via propagate.extract(message.headers)).
	if _, ok := tbl["traceparent"].(string); !ok {
		t.Errorf("underlying table value is %T, want string", tbl["traceparent"])
	}

	if got := c.Get("missing"); got != "" {
		t.Errorf("Get(missing) = %q, want empty", got)
	}

	// Non-string values (possible in an amqp.Table) must not panic.
	tbl["numeric"] = int32(42)
	if got := c.Get("numeric"); got != "" {
		t.Errorf("Get(numeric) = %q, want empty for non-string value", got)
	}

	keys := c.Keys()
	slices.Sort(keys)
	if want := []string{"numeric", "traceparent"}; !slices.Equal(keys, want) {
		t.Errorf("Keys() = %v, want %v", keys, want)
	}
}
