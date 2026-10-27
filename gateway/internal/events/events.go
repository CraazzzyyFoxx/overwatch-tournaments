// Package events bridges the existing Redis pub/sub realtime bus to the
// WebSocket hub. It is a port of realtime-service's pubsub_listener: it
// PSUBSCRIBEs to "realtime:*" and relays each message verbatim to subscribers
// of the corresponding topic. Keeping Redis (rather than RabbitMQ) here means
// every existing publisher (tournament/balancer/draft) works unchanged.
package events

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// ChannelPrefix matches shared/services/realtime_topics.REALTIME_CHANNEL_PREFIX.
const ChannelPrefix = "realtime:"

const reconnectDelay = 2 * time.Second

// Broadcaster receives a topic + pre-serialized frame for fan-out.
type Broadcaster interface {
	Broadcast(topic string, payload []byte)
}

// Resetter is implemented by a Broadcaster whose state is only as current as
// the frames it has seen (a cache the bus invalidates, sockets the bus feeds).
// Subscriber calls Reset after its Redis subscription was lost and
// re-established: what was published in between never arrived and nothing
// replays it.
type Resetter interface {
	Reset()
}

// Fanout composes several Broadcasters into one: every message is delivered
// to each in order, and Reset reaches every leg that is a Resetter in the
// same order. Used to feed the realtime bus to both the WebSocket hub and the
// gateway response cache's invalidator from a single subscription.
func Fanout(bs ...Broadcaster) Broadcaster { return fanout(bs) }

type fanout []Broadcaster

func (f fanout) Broadcast(topic string, payload []byte) {
	for _, b := range f {
		b.Broadcast(topic, payload)
	}
}

// Reset implements Resetter.
func (f fanout) Reset() {
	for _, b := range f {
		if r, ok := b.(Resetter); ok {
			r.Reset()
		}
	}
}

// Subscriber consumes the realtime Redis bus and feeds the hub.
type Subscriber struct {
	client *redis.Client
	hub    Broadcaster
	log    *slog.Logger
	// subscribed is set by the first subscription confirmation; every later
	// one is a re-subscription after a lost connection. Only Run's goroutine
	// touches it.
	subscribed bool
}

// New returns a Subscriber.
func New(client *redis.Client, hub Broadcaster, log *slog.Logger) *Subscriber {
	return &Subscriber{client: client, hub: hub, log: log}
}

// Run subscribes and relays until ctx is cancelled, reconnecting on failure.
//
// go-redis's PubSub also reconnects and re-subscribes on its own, and only the
// subscription confirmation on the new connection shows it happened — hence
// ChannelWithSubscriptions, not Channel, which drops confirmations.
func (s *Subscriber) Run(ctx context.Context) error {
	pattern := ChannelPrefix + "*"
	for {
		pubsub := s.client.PSubscribe(ctx, pattern)
		err := s.consume(ctx, pubsub.ChannelWithSubscriptions())
		_ = pubsub.Close()

		if ctx.Err() != nil {
			return ctx.Err()
		}
		s.log.Warn("realtime subscription ended; reconnecting", "err", err)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(reconnectDelay):
		}
	}
}

func (s *Subscriber) consume(ctx context.Context, ch <-chan any) error {
	for {
		select {
		case <-ctx.Done():
			return nil
		case msg, ok := <-ch:
			if !ok {
				return errors.New("redis pubsub channel closed")
			}
			switch msg := msg.(type) {
			case *redis.Message:
				s.dispatch(msg.Channel, []byte(msg.Payload))
			case *redis.Subscription:
				s.confirmed()
			}
		}
	}
}

// confirmed handles a subscription confirmation. The first one is the bus
// coming up. Any later one — go-redis re-subscribing on a fresh connection, or
// Run's own reconnect — ends a stretch with no subscription, so the legs drop
// what they derived from the bus before the next frame reaches them. It runs
// on the relay loop, ahead of every frame the new subscription delivers.
func (s *Subscriber) confirmed() {
	if s.subscribed {
		s.log.Warn("realtime subscription re-established; resetting state that missed frames")
		if r, ok := s.hub.(Resetter); ok {
			r.Reset()
		}
	}
	s.subscribed = true
}

// dispatch derives the topic from the channel name and relays the raw frame.
func (s *Subscriber) dispatch(channel string, payload []byte) {
	topic := strings.TrimPrefix(channel, ChannelPrefix)
	if topic == "" || topic == channel {
		s.log.Warn("dropping realtime message with unexpected channel", "channel", channel)
		return
	}
	s.hub.Broadcast(topic, payload)
}
