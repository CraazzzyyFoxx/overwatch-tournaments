package identity

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	queueHTTPTunnel = "rpc.identity.http"
	// tunnelTimeout is longer than rpcTimeout: tunneled requests include avatar
	// uploads (S3 round-trip inside identity-svc).
	tunnelTimeout = 30 * time.Second
	// maxTunnelBody caps a tunneled request body before it is buffered + base64'd
	// into the RPC message. Avatars are small; this guards memory/AMQP size.
	maxTunnelBody = 20 << 20 // 20 MiB
)

// tunnelResponse is the raw HTTP response returned by rpc.identity.http (NOT the
// {ok,data,error} envelope).
type tunnelResponse struct {
	Status  int        `json:"status"`
	Headers [][]string `json:"headers"`
	Body    string     `json:"body"`
}

// tunnelDropResponseHeaders are hop-by-hop headers the gateway must not copy
// verbatim — Go recomputes them when it writes the response.
var tunnelDropResponseHeaders = map[string]bool{
	"content-length":    true,
	"transfer-encoding": true,
	"connection":        true,
}

// Tunnel forwards a not-yet-typed /api/auth/* request to identity-svc's
// in-process ASGI app over RPC and relays the raw HTTP response. It replaces the
// reverse-proxy fallback to auth-service for /api/auth/*, so auth-service can be
// decommissioned. Typed routes (login/validate/oauth/api-keys/...) are matched
// first by the mux; everything else under /api/auth/ lands here.
func (h *Handler) Tunnel(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxTunnelBody+1))
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "could not read request body")
		return
	}
	if len(raw) > maxTunnelBody {
		writeDetail(w, http.StatusRequestEntityTooLarge, "request body too large")
		return
	}

	// identity-svc's router is root-relative; strip the /api/auth prefix so paths
	// arrive as /rbac/..., /player/..., /me/avatar, etc.
	path := strings.TrimPrefix(r.URL.Path, "/api/auth")
	if path == "" || path[0] != '/' {
		path = "/" + path
	}

	headers := make(map[string]string, len(r.Header))
	for k, vs := range r.Header {
		headers[k] = strings.Join(vs, ",")
	}

	reqBody, _ := json.Marshal(map[string]any{
		"method":  r.Method,
		"path":    path,
		"query":   r.URL.RawQuery,
		"headers": headers,
		"body":    base64.StdEncoding.EncodeToString(raw),
	})

	ctx, cancel := context.WithTimeout(r.Context(), tunnelTimeout)
	defer cancel()

	respRaw, err := h.rpc.Call(ctx, queueHTTPTunnel, reqBody)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			h.log.Error("identity tunnel unavailable", "path", path, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "identity service unavailable")
			return
		}
		h.log.Error("identity tunnel failed", "path", path, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "identity service timeout")
		return
	}

	var tr tunnelResponse
	if err := json.Unmarshal(respRaw, &tr); err != nil {
		h.log.Error("invalid tunnel response", "path", path, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid identity response")
		return
	}

	for _, kv := range tr.Headers {
		if len(kv) != 2 || tunnelDropResponseHeaders[strings.ToLower(kv[0])] {
			continue
		}
		w.Header().Add(kv[0], kv[1])
	}
	status := tr.Status
	if status == 0 {
		status = http.StatusBadGateway
	}
	w.WriteHeader(status)
	if tr.Body != "" {
		if decoded, derr := base64.StdEncoding.DecodeString(tr.Body); derr == nil {
			_, _ = w.Write(decoded)
		}
	}
}
