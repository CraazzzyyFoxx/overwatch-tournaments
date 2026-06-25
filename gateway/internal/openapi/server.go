package openapi

import (
	"bytes"
	"html/template"
	"net/http"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// Route paths. The spec + UI live outside the guarded /api/{v1,auth,analytics,
// balancer}/ namespaces and outside /ws + /health, so they reach the gateway
// (nginx proxies everything here) and win over the "/" frontend proxy by
// ServeMux specificity.
const (
	publicSpecPath = "/api/openapi.json"
	publicUIPath   = "/api/docs"
	adminSpecPath  = "/api/openapi.admin.json"
	adminUIPath    = "/api/docs/admin"
)

// Server serves the pre-built specs and Scalar pages. Specs and pages are
// rendered once at construction and written verbatim per request.
type Server struct {
	cfg        config.Docs
	publicSpec []byte
	adminSpec  []byte
	publicPage []byte
	adminPage  []byte
}

// New builds the public/admin specs and their Scalar pages. The public spec is
// built from publicGroups, the admin spec from adminGroups (admin-only).
func New(cfg config.Docs, info Info, publicGroups, adminGroups []Group) *Server {
	adminInfo := info
	adminInfo.Title = info.Title + " — Admin"

	return &Server{
		cfg:        cfg,
		publicSpec: Build(info, publicGroups),
		adminSpec:  Build(adminInfo, adminGroups),
		publicPage: page(info.Title, publicSpecPath, cfg.CDN),
		adminPage:  page(adminInfo.Title, adminSpecPath, cfg.CDN),
	}
}

// Register mounts the docs routes on the REST mux. No-op when docs are disabled.
// The admin routes are always registered but return 404 when AdminEnabled is
// false, so an unmatched /api/docs/admin never falls through to the frontend.
func (s *Server) Register(mux *http.ServeMux) {
	if !s.cfg.Enabled {
		return
	}
	mux.HandleFunc("GET "+publicSpecPath, jsonHandler(s.publicSpec))
	mux.HandleFunc("GET "+publicUIPath, htmlHandler(s.publicPage))
	mux.HandleFunc("GET "+adminSpecPath, s.gatedAdmin(jsonHandler(s.adminSpec)))
	mux.HandleFunc("GET "+adminUIPath, s.gatedAdmin(htmlHandler(s.adminPage)))
}

func (s *Server) gatedAdmin(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.cfg.AdminEnabled {
			notFound(w)
			return
		}
		next(w, r)
	}
}

func jsonHandler(body []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	}
}

func htmlHandler(body []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(body)
	}
}

func notFound(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusNotFound)
	_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
}

// pageTmpl renders the Scalar standalone page. html/template escapes the title
// (HTML), the CDN URL (attribute) and the spec URL (JS string) per context.
var pageTmpl = template.Must(template.New("scalar").Parse(`<!doctype html>
<html>
<head>
<title>{{.Title}}</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<div id="app"></div>
<script src="{{.CDN}}"></script>
<script>
Scalar.createApiReference('#app', { url: {{.SpecURL}} })
</script>
</body>
</html>`))

func page(title, specURL, cdn string) []byte {
	var buf bytes.Buffer
	_ = pageTmpl.Execute(&buf, map[string]string{
		"Title":   title,
		"SpecURL": specURL,
		"CDN":     cdn,
	})
	return buf.Bytes()
}
