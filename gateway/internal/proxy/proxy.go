// Package proxy reverse-proxies REST traffic to the existing services using
// longest-prefix path routing. Paths are preserved (no stripping), and the
// original Host is forwarded.
package proxy

import (
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sort"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

type route struct {
	prefix string
	proxy  *httputil.ReverseProxy
}

// Proxy routes requests to upstream services by longest path prefix.
type Proxy struct {
	routes []route
}

// New builds the proxy from the configured upstreams.
func New(up config.Upstreams) (*Proxy, error) {
	specs := []struct{ prefix, target string }{
		// All backend domains (/api/v1/* for tournament+app+parser, /api/auth/* via
		// identity-svc, /api/analytics/* via analytics-svc, /api/balancer/* via
		// balancer-worker) are served by the gateway's typed RPC routes — never
		// proxied; per-prefix 404 guards in main.go catch unmatched paths. The HTTP
		// parser/analytics/balancer services are decommissioned. Only the frontend
		// is reverse-proxied now.
		{"/api/account", up.Frontend},
		{"/", up.Frontend},
	}

	p := &Proxy{}
	for _, s := range specs {
		rp, err := newReverseProxy(s.target)
		if err != nil {
			return nil, fmt.Errorf("upstream for %s: %w", s.prefix, err)
		}
		p.routes = append(p.routes, route{prefix: s.prefix, proxy: rp})
	}

	// Longest prefix first so the most specific route wins.
	sort.SliceStable(p.routes, func(i, j int) bool {
		return len(p.routes[i].prefix) > len(p.routes[j].prefix)
	})
	return p, nil
}

func newReverseProxy(target string) (*httputil.ReverseProxy, error) {
	u, err := url.Parse(target)
	if err != nil {
		return nil, err
	}
	if u.Scheme == "" || u.Host == "" {
		return nil, fmt.Errorf("invalid upstream url %q", target)
	}
	// NewSingleHostReverseProxy preserves the request path (target has no path)
	// and leaves req.Host untouched, forwarding the original Host header.
	return httputil.NewSingleHostReverseProxy(u), nil
}

func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Never forward client-supplied trace context past the public edge; inject
	// the gateway's own span context instead (no-op when tracing is disabled).
	// ReverseProxy clones the header map for the outbound request, so mutating
	// the inbound headers here is the standard injection point.
	r.Header.Del("traceparent")
	r.Header.Del("tracestate")
	otel.GetTextMapPropagator().Inject(r.Context(), propagation.HeaderCarrier(r.Header))
	for _, rt := range p.routes {
		if matchPrefix(r.URL.Path, rt.prefix) {
			rt.proxy.ServeHTTP(w, r)
			return
		}
	}
	http.NotFound(w, r) // unreachable: "/" always matches
}

// matchPrefix does segment-aware prefix matching so "/api/v1" matches
// "/api/v1" and "/api/v1/..." but not "/api/v1xyz".
func matchPrefix(path, prefix string) bool {
	if prefix == "/" {
		return true
	}
	return path == prefix || strings.HasPrefix(path, prefix+"/")
}
