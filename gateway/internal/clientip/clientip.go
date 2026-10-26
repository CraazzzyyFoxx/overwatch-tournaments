// Package clientip extracts the trusted client IP from a request reaching the
// gateway behind the nginx edge.
//
// nginx sets X-Real-IP to the connecting peer ($remote_addr) and appends that
// peer as the LAST hop of X-Forwarded-For (via $proxy_add_x_forwarded_for). The
// left-most X-Forwarded-For entries are therefore client-supplied and trivially
// spoofable, so we must never trust them. And any of it is believable only from
// a trusted proxy: a caller reaching the gateway directly (the dev compose
// publishes its port) would otherwise pick its own rate-limit bucket and
// anonymous-WebSocket allowance per request. So the socket peer decides: an
// untrusted peer is the client; a trusted one is a proxy, whose X-Real-IP wins,
// then the right-most X-Forwarded-For hop that is not itself a proxy.
package clientip

import (
	"net"
	"net/http"
	"net/netip"
	"strings"
)

// trustedProxies are the peers whose forwarding headers From believes: by
// default loopback and private ranges, where a same-host or same-network
// reverse proxy (nginx on the compose network) connects from.
var trustedProxies = []netip.Prefix{
	netip.MustParsePrefix("127.0.0.0/8"),
	netip.MustParsePrefix("::1/128"),
	netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.168.0.0/16"),
	netip.MustParsePrefix("fc00::/7"),
}

// SetTrustedProxies replaces the default trusted proxy prefixes. Call once at
// startup, before serving: From reads them unsynchronized.
func SetTrustedProxies(p []netip.Prefix) { trustedProxies = p }

func trusted(a netip.Addr) bool {
	for _, p := range trustedProxies {
		if p.Contains(a) {
			return true
		}
	}
	return false
}

// parseAddr parses one address in canonical form: IPv4-mapped IPv6 unmapped
// (a dual-stack listener reports IPv4 peers that way, and no IPv4 prefix
// contains the mapped form) and the zone dropped (a zoned address matches no
// prefix).
func parseAddr(s string) (netip.Addr, bool) {
	a, err := netip.ParseAddr(strings.TrimSpace(s))
	if err != nil {
		return netip.Addr{}, false
	}
	return a.Unmap().WithZone(""), true
}

// From returns the trusted client IP for r. It never trusts the left-most,
// client-controlled X-Forwarded-For entry, nor vendor CDN headers
// (CF-Connecting-IP / True-Client-IP / X-Client-IP): Cloudflare is not used here
// and those headers are spoofable when the gateway is reached directly.
func From(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer, ok := parseAddr(host)
	if !ok {
		return host // not an IP peer (e.g. a unix socket): nothing to trust
	}
	if !trusted(peer) {
		return peer.String()
	}
	if a, ok := parseAddr(r.Header.Get("X-Real-IP")); ok {
		return a.String()
	}
	// Walk right to left: each hop was appended by the proxy one step closer,
	// so the first hop that is not a proxy is the client. A hop that does not
	// parse ends the trustworthy chain at the proxy that wrote it; a chain of
	// proxies only (a client on the private network) ends at the left-most.
	client := peer
	values := r.Header.Values("X-Forwarded-For")
	for i := len(values) - 1; i >= 0; i-- {
		hops := strings.Split(values[i], ",")
		for j := len(hops) - 1; j >= 0; j-- {
			a, ok := parseAddr(hops[j])
			if !ok {
				return client.String()
			}
			if client = a; !trusted(a) {
				return a.String()
			}
		}
	}
	return client.String()
}

// UserAgent returns the ORIGINAL client user-agent. nginx preserves it in
// X-Original-User-Agent when it rewrites User-Agent for an upstream hop, so that
// header wins; otherwise the request's own User-Agent stands.
//
// Lives here rather than beside either caller because the identity handlers and
// the generic edge dispatcher both stamp this onto outgoing RPC bodies, and two
// copies of "which header do we trust" is exactly the pair that drifts.
func UserAgent(r *http.Request) string {
	if v := strings.TrimSpace(r.Header.Get("X-Original-User-Agent")); v != "" {
		return v
	}
	return r.Header.Get("User-Agent")
}
