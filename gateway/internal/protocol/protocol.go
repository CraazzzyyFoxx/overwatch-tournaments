// Package protocol implements the realtime WebSocket wire format.
//
// It is a faithful port of backend/shared/schemas/realtime.py: the same client
// ops (subscribe/unsubscribe/ping/publish) and server frames
// (subscribed/error/event/pong) with identical JSON field names, so the existing
// frontend client (frontend/src/services/realtime.service.ts) works unchanged.
package protocol

import (
	"encoding/json"
	"time"
)

// Limits mirrored from the Python realtime-service.
const (
	MaxTopicLen      = 255
	MaxEventTypeLen  = 64
	MaxPublishFields = 32
)

// Envelope is a WorkspaceEventEnvelope: the event payload pushed inside an
// "event" frame. event_id == 0 marks an ephemeral event (presence / client
// publish) that never advances the replay cursor.
type Envelope struct {
	EventID       int64          `json:"event_id"`
	EventType     string         `json:"event_type"`
	SchemaVersion int            `json:"schema_version"`
	OccurredAt    time.Time      `json:"occurred_at"`
	ActorUserID   *int64         `json:"actor_user_id"`
	Data          map[string]any `json:"data"`
}

// ClientOp is a single inbound frame from a WebSocket client. A single struct
// covers all op types; Validate enforces the per-op required fields, matching
// the Pydantic discriminated union.
type ClientOp struct {
	Op           string         `json:"op"`
	Topic        string         `json:"topic"`
	AfterEventID *int64         `json:"after_event_id"`
	EventType    string         `json:"event_type"`
	Data         map[string]any `json:"data"`
}

// ProtocolError is a structured parse/validation failure that maps to an
// "error" frame sent back to the client.
type ProtocolError struct {
	Code    string
	Message string
	Topic   *string
}

func (e *ProtocolError) Error() string { return e.Message }

// ParseClientOp decodes and validates a raw client frame.
func ParseClientOp(raw []byte) (*ClientOp, *ProtocolError) {
	// Probe first so we can surface the topic on a malformed frame even when
	// strict decoding into ClientOp would fail on a field type mismatch.
	var probe map[string]any
	if err := json.Unmarshal(raw, &probe); err != nil {
		return nil, &ProtocolError{Code: "invalid_json", Message: "Frame must be valid JSON"}
	}

	var op ClientOp
	if err := json.Unmarshal(raw, &op); err != nil {
		return nil, &ProtocolError{
			Code:    "invalid_frame",
			Message: "Frame does not match realtime protocol",
			Topic:   topicFromProbe(probe),
		}
	}
	if perr := op.validate(probe); perr != nil {
		return nil, perr
	}
	return &op, nil
}

func (op *ClientOp) validate(probe map[string]any) *ProtocolError {
	invalid := func() *ProtocolError {
		return &ProtocolError{
			Code:    "invalid_frame",
			Message: "Frame does not match realtime protocol",
			Topic:   topicFromProbe(probe),
		}
	}

	switch op.Op {
	case "ping":
		return nil
	case "subscribe":
		if !validTopic(op.Topic) {
			return invalid()
		}
		if op.AfterEventID != nil && *op.AfterEventID < 0 {
			return invalid()
		}
		return nil
	case "unsubscribe":
		if !validTopic(op.Topic) {
			return invalid()
		}
		return nil
	case "publish":
		if !validTopic(op.Topic) {
			return invalid()
		}
		if len(op.EventType) < 1 || len(op.EventType) > MaxEventTypeLen {
			return invalid()
		}
		if len(op.Data) > MaxPublishFields {
			return invalid()
		}
		return nil
	default:
		return invalid()
	}
}

func validTopic(topic string) bool {
	return len(topic) >= 1 && len(topic) <= MaxTopicLen
}

func topicFromProbe(probe map[string]any) *string {
	if probe == nil {
		return nil
	}
	if t, ok := probe["topic"].(string); ok {
		return &t
	}
	return nil
}

// --- Server frames (serialized to JSON bytes) ---

type errorFrame struct {
	Op      string  `json:"op"`
	Topic   *string `json:"topic"`
	Code    string  `json:"code"`
	Message string  `json:"message"`
}

type eventFrame struct {
	Op    string   `json:"op"`
	Topic string   `json:"topic"`
	Event Envelope `json:"event"`
}

type subscribedFrame struct {
	Op     string `json:"op"`
	Topic  string `json:"topic"`
	Cursor int64  `json:"cursor"`
}

type pongFrame struct {
	Op string `json:"op"`
}

// ErrorFrame builds an "error" frame. topic may be nil (serialized as null).
func ErrorFrame(code, message string, topic *string) []byte {
	return mustMarshal(errorFrame{Op: "error", Topic: topic, Code: code, Message: message})
}

// EventFrame builds an "event" frame carrying the given envelope.
func EventFrame(topic string, env Envelope) []byte {
	return mustMarshal(eventFrame{Op: "event", Topic: topic, Event: env})
}

// SubscribedFrame builds a "subscribed" acknowledgement frame.
func SubscribedFrame(topic string, cursor int64) []byte {
	return mustMarshal(subscribedFrame{Op: "subscribed", Topic: topic, Cursor: cursor})
}

// PongFrame builds a "pong" frame.
func PongFrame() []byte {
	return mustMarshal(pongFrame{Op: "pong"})
}

// EventFrameTopic extracts the topic from a raw "event" frame (as published on
// Redis) without fully decoding the envelope, so the fan-in path can route the
// bytes verbatim.
func EventFrameTopic(raw []byte) (string, bool) {
	var probe struct {
		Topic string `json:"topic"`
	}
	if err := json.Unmarshal(raw, &probe); err != nil || probe.Topic == "" {
		return "", false
	}
	return probe.Topic, true
}

func mustMarshal(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		// Server frames are built from fully-typed structs; marshal cannot fail.
		panic(err)
	}
	return b
}
