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

// Fanout composes several Broadcasters into one: every message is delivered
// to each in order. Used to feed the realtime bus to both the WebSocket hub
// and the gateway response cache's invalidator from a single subscription.
func Fanout(bs ...Broadcaster) Broadcaster { return fanout(bs) }

type fanout []Broadcaster

func (f fanout) Broadcast(topic string, payload []byte) {
	for _, b := range f {
		b.Broadcast(topic, payload)
	}
}

// Subscriber consumes the realtime Redis bus and feeds the hub.
type Subscriber struct {
	client *redis.Client
	hub    Broadcaster
	log    *slog.Logger
}

// New returns a Subscriber.
func New(client *redis.Client, hub Broadcaster, log *slog.Logger) *Subscriber {
	return &Subscriber{client: client, hub: hub, log: log}
}

// Run subscribes and relays until ctx is cancelled, reconnecting on failure.
func (s *Subscriber) Run(ctx context.Context) error {
	pattern := ChannelPrefix + "*"
	for {
		pubsub := s.client.PSubscribe(ctx, pattern)
		err := s.consume(ctx, pubsub.Channel())
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

func (s *Subscriber) consume(ctx context.Context, ch <-chan *redis.Message) error {
	for {
		select {
		case <-ctx.Done():
			return nil
		case msg, ok := <-ch:
			if !ok {
				return errors.New("redis pubsub channel closed")
			}
			s.dispatch(msg.Channel, []byte(msg.Payload))
		}
	}
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
