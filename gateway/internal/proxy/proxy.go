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
		// /api/v1/* (tournament + app + parser) is served by the gateway's typed
		// RPC routes into the workers — never proxied; the /api/v1/ 404 guard in
		// main.go catches unmatched paths. /api/auth/* likewise via identity-svc.
		// parser + analytics HTTP are decommissioned (parser folded into /api/v1;
		// /api/analytics is fully served by typed RPC into analytics-svc), so neither
		// is proxied. The /api/balancer fallback below serves only un-migrated
		// (non-typed) balancer endpoints on their legacy paths.
		{"/api/balancer", up.Balancer},
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
