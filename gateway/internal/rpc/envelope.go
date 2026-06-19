package rpc

import "encoding/json"

// Envelope is the reply shape every identity-svc RPC method returns:
//
//	{"ok": true, "data": {...}}                 — success
//	{"ok": false, "error": {"code","message"}}  — failure
type Envelope struct {
	OK    bool            `json:"ok"`
	Data  json.RawMessage `json:"data"`
	Error *EnvelopeError  `json:"error"`
}

// EnvelopeError carries a machine code (mapped to an HTTP status) and a message.
type EnvelopeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// StatusForCode maps an envelope error code to an HTTP status, preserving the
// auth-service contract's status codes.
func StatusForCode(code string) int {
	switch code {
	case "bad_request":
		return 400
	case "unauthorized":
		return 401
	case "forbidden":
		return 403
	case "not_found":
		return 404
	case "conflict":
		return 409
	case "gone":
		return 410
	case "unprocessable":
		return 422
	case "payload_too_large":
		return 413
	case "rate_limited":
		return 429
	default:
		return 500
	}
}
