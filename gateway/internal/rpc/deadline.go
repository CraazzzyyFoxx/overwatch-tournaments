package rpc

import (
	"context"
	"strconv"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// deadlineHeader carries the absolute request deadline (unix epoch, ms) to the
// worker. The FastStream deadline-drop middleware reads the same name — keep
// the two in sync (backend/shared/rpc/deadline.py).
const deadlineHeader = "x-deadline-ms"

// buildPublishing assembles the AMQP message for one RPC request. When ctx
// carries a deadline the message gets a matching per-message TTL, so RabbitMQ
// itself drops it if it is still queued after the gateway has given up, plus
// the x-deadline-ms header for the worker-side stale check (messages already
// prefetched by a consumer are past TTL's reach). All RPC messages get their
// TTL from the same formula, so FIFO order matches expiry order and RabbitMQ's
// head-of-queue expiration is exact.
//
// headers carries the caller's W3C trace context + correlation id (see
// rpc.go). The deadline header is merged into it rather than replacing it, so
// trace propagation survives; pass nil when there are none.
func buildPublishing(ctx context.Context, id, replyQueue string, body []byte, headers amqp.Table) amqp.Publishing {
	pub := amqp.Publishing{
		ContentType:   contentTypeJSON,
		CorrelationId: id,
		ReplyTo:       replyQueue,
		Body:          body,
	}
	if deadline, ok := ctx.Deadline(); ok {
		ms := time.Until(deadline).Milliseconds()
		if ms < 1 {
			ms = 1 // deadline already passed: publish with minimal TTL, broker drops it at the head
		}
		pub.Expiration = strconv.FormatInt(ms, 10)
		if headers == nil {
			headers = amqp.Table{}
		}
		headers[deadlineHeader] = deadline.UnixMilli()
	}
	if len(headers) > 0 {
		pub.Headers = headers
	}
	return pub
}
