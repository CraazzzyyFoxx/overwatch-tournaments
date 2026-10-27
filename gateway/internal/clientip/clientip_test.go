package clientip

import (
	"net/http/httptest"
	"net/netip"
	"testing"
)

func TestFrom(t *testing.T) {
	cases := []struct {
		name       string
		remoteAddr string
		realIP     string
		xff        []string
		want       string
	}{
		// A direct caller cannot pick its own bucket by naming one.
		{"untrusted peer, spoofed X-Real-IP", "203.0.113.9:4000", "6.6.6.6", nil, "203.0.113.9"},
		{"untrusted peer, spoofed XFF", "203.0.113.9:4000", "", []string{"6.6.6.6"}, "203.0.113.9"},
		{"trusted peer, X-Real-IP wins", "172.18.0.5:4000", "198.51.100.7", []string{"6.6.6.6, 198.51.100.8"}, "198.51.100.7"},
		{"trusted peer, unparseable X-Real-IP falls to XFF", "10.0.0.2:4000", "unknown", []string{"198.51.100.8"}, "198.51.100.8"},
		{"trusted peer, no headers", "127.0.0.1:4000", "", nil, "127.0.0.1"},
		// Right-most hop that is not itself a proxy; the left-most is the
		// client's own claim.
		{"XFF skips trusted hops", "10.0.0.2:4000", "", []string{"6.6.6.6, 198.51.100.8, 10.0.0.3"}, "198.51.100.8"},
		{"XFF across header lines", "10.0.0.2:4000", "", []string{"6.6.6.6", "198.51.100.8, 10.0.0.3"}, "198.51.100.8"},
		{"XFF of proxies only ends at the left-most", "10.0.0.2:4000", "", []string{"192.168.1.20, 10.0.0.3"}, "192.168.1.20"},
		{"XFF garbage stops at the proxy that wrote it", "10.0.0.2:4000", "", []string{"6.6.6.6, junk, 10.0.0.3"}, "10.0.0.3"},
		// Canonical form: a dual-stack listener reports IPv4 peers mapped.
		{"mapped trusted peer", "[::ffff:10.0.0.2]:4000", "::ffff:198.51.100.7", nil, "198.51.100.7"},
		{"mapped untrusted peer", "[::ffff:203.0.113.9]:4000", "6.6.6.6", nil, "203.0.113.9"},
		{"IPv6 ULA proxy", "[fd00::2]:4000", "2001:db8::7", nil, "2001:db8::7"},
		{"bare RemoteAddr", "203.0.113.9", "6.6.6.6", nil, "203.0.113.9"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", "/", nil)
			r.RemoteAddr = tc.remoteAddr
			if tc.realIP != "" {
				r.Header.Set("X-Real-IP", tc.realIP)
			}
			for _, v := range tc.xff {
				r.Header.Add("X-Forwarded-For", v)
			}
			if got := From(r); got != tc.want {
				t.Fatalf("From = %q, want %q", got, tc.want)
			}
		})
	}
}

// SetTrustedProxies replaces the defaults: a private peer outside the
// configured list is a client like any other.
func TestSetTrustedProxies(t *testing.T) {
	defaults := trustedProxies
	t.Cleanup(func() { SetTrustedProxies(defaults) })
	SetTrustedProxies([]netip.Prefix{netip.MustParsePrefix("203.0.113.0/24")})

	r := httptest.NewRequest("GET", "/", nil)
	r.Header.Set("X-Real-IP", "198.51.100.7")
	r.RemoteAddr = "203.0.113.9:4000"
	if got := From(r); got != "198.51.100.7" {
		t.Fatalf("configured proxy: From = %q, want the X-Real-IP", got)
	}
	r.RemoteAddr = "10.0.0.2:4000"
	if got := From(r); got != "10.0.0.2" {
		t.Fatalf("peer outside the configured list: From = %q, want the peer", got)
	}
}
