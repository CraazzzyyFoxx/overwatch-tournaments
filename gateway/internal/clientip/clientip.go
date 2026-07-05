// Package clientip extracts the trusted client IP from a request reaching the
// gateway behind the nginx edge.
//
// nginx sets X-Real-IP to the connecting peer ($remote_addr) and appends that
// peer as the LAST hop of X-Forwarded-For (via $proxy_add_x_forwarded_for). The
// left-most X-Forwarded-For entries are therefore client-supplied and trivially
// spoofable, so we must never trust them. We trust X-Real-IP first, then the
// right-most X-Forwarded-For hop, then the raw remote address.
package clientip

import (
	"net"
	"net/http"
	"strings"
)

// From returns the trusted client IP for r. It never trusts the left-most,
// client-controlled X-Forwarded-For entry, nor vendor CDN headers
// (CF-Connecting-IP / True-Client-IP / X-Client-IP): Cloudflare is not used here
// and those headers are spoofable when the gateway is reached directly.
func From(r *http.Request) string {
	if v := strings.TrimSpace(r.Header.Get("X-Real-IP")); v != "" && !strings.EqualFold(v, "unknown") {
		return v
	}
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		for i := len(parts) - 1; i >= 0; i-- {
			candidate := strings.TrimSpace(parts[i])
			if candidate != "" && !strings.EqualFold(candidate, "unknown") {
				return candidate
			}
		}
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}
