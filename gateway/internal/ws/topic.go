package ws

import "strings"

// Event types and limits ported from the Python realtime-service.
const (
	// BalancerDrag is the only event type clients may publish over the socket.
	BalancerDrag = "balancer.drag"
	// BalancerPresence carries the live subscriber list for a balancer topic.
	BalancerPresence = "balancer.presence"
	// DraftPresence carries authenticated users and the anonymous connection count.
	DraftPresence = "draft.presence"

	// MaxClientFrameBytes caps a single inbound frame before JSON parsing.
	MaxClientFrameBytes = 8192
	// MaxPublishPerSecond throttles client-originated ephemeral frames.
	MaxPublishPerSecond = 60

	readLimit = 65536
)

// IsPresenceTopic reports whether a topic broadcasts WebSocket-derived presence.
func IsPresenceTopic(topic string) bool {
	return strings.HasSuffix(topic, ":balancer") || strings.HasSuffix(topic, ":draft")
}

func presenceEventType(topic string) string {
	if strings.HasSuffix(topic, ":draft") {
		return DraftPresence
	}
	return BalancerPresence
}
