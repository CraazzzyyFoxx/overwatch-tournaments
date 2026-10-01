package openapi

import (
	"bytes"
	"encoding/json"
	"html/template"
	"net/http"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// Route paths. The spec + UI live outside /api/v1 and outside /ws + /health,
// and win over the REST mux's "/" 404 catch-all by ServeMux specificity.
const (
	publicSpecPath   = "/api/openapi.json"
	publicUIPath     = "/api/docs"
	adminSpecPath    = "/api/openapi.admin.json"
	adminUIPath      = "/api/docs/admin"
	publicV2SpecPath = "/api/openapi.v2.json"
	adminV2SpecPath  = "/api/openapi.v2.admin.json"
)

// Server serves the pre-built specs and Scalar pages. Specs and pages are
// rendered once at construction and written verbatim per request.
type Server struct {
	cfg          config.Docs
	publicSpec   []byte
	adminSpec    []byte
	publicV2Spec []byte
	adminV2Spec  []byte
	publicPage   []byte
	adminPage    []byte
}

// New builds the public/admin specs and their Scalar pages. The public spec is
// built from publicGroups, the admin spec from adminGroups (admin-only).
func New(cfg config.Docs, info Info, publicGroups, adminGroups []Group) *Server {
	adminInfo := info
	adminInfo.Title = info.Title + " — Admin"

	return &Server{
		cfg:          cfg,
		publicSpec:   Build(info, publicGroups),
		adminSpec:    Build(adminInfo, adminGroups),
		publicV2Spec: BuildV2(info, publicGroups),
		adminV2Spec:  BuildV2(adminInfo, adminGroups),
		publicPage: page(info.Title, cfg.CDN, []source{
			{Title: "v1", Slug: "v1", URL: publicSpecPath},
			{Title: "v2", Slug: "v2", URL: publicV2SpecPath},
		}),
		adminPage: page(adminInfo.Title, cfg.CDN, []source{
			{Title: "v1", Slug: "v1", URL: adminSpecPath},
			{Title: "v2", Slug: "v2", URL: adminV2SpecPath},
		}),
	}
}

// Register mounts the docs routes on the REST mux. No-op when docs are disabled.
// The admin routes are always registered but return 404 when AdminEnabled is
// false.
func (s *Server) Register(mux *http.ServeMux) {
	if !s.cfg.Enabled {
		return
	}
	mux.HandleFunc("GET "+publicSpecPath, jsonHandler(s.publicSpec))
	mux.HandleFunc("GET "+publicUIPath, htmlHandler(s.publicPage))
	mux.HandleFunc("GET "+adminSpecPath, s.gatedAdmin(jsonHandler(s.adminSpec)))
	mux.HandleFunc("GET "+adminUIPath, s.gatedAdmin(htmlHandler(s.adminPage)))
	mux.HandleFunc("GET "+publicV2SpecPath, jsonHandler(s.publicV2Spec))
	mux.HandleFunc("GET "+adminV2SpecPath, s.gatedAdmin(jsonHandler(s.adminV2Spec)))
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
// (HTML) and the CDN URL (attribute). Config is encoding/json output marked
// template.JS so the sources array is valid JS.
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
Scalar.createApiReference('#app', {{.Config}})
</script>
</body>
</html>`))

type source struct {
	Title string `json:"title"`
	Slug  string `json:"slug"`
	URL   string `json:"url"`
}

func page(title, cdn string, sources []source) []byte {
	cfg, _ := json.Marshal(map[string]any{
		"sources":     sources,
		"persistAuth": true,
	})
	var buf bytes.Buffer
	_ = pageTmpl.Execute(&buf, map[string]any{
		"Title":  title,
		"CDN":    cdn,
		"Config": template.JS(cfg),
	})
	return buf.Bytes()
}
