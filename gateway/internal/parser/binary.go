package parser

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	// Matches the edge dispatcher's RPC ceiling (old Kong edge allowance).
	binaryRPCTimeout = 120 * time.Second
	// parser's RequestSizeLimitMiddleware allows 50 MiB (log-file uploads).
	maxUpload = 50 << 20
)

// Binary serves the parser-service endpoints the generic JSON edge.Dispatcher
// can't: the admin match-log upload (multipart, possibly many files[] -> base64
// into the RPC body). Permission is enforced in the worker; the gateway only
// resolves + injects identity for the authenticated route.
type Binary struct {
	rpc      edge.RPCCaller
	identity edge.IdentityResolver
	log      *slog.Logger
}

// NewBinary builds the binary handler set. identity must be non-nil (the upload
// route is authenticated).
func NewBinary(caller edge.RPCCaller, identity edge.IdentityResolver, log *slog.Logger) *Binary {
	return &Binary{rpc: caller, identity: identity, log: log}
}

// AdminLogsUpload: POST /api/v1/admin/logs/upload. Reads the multipart form
// (tournament_id, optional encounter_id, one or more files[]) and base64-encodes
// each file into the RPC body for rpc.parser.logs.upload.
func (b *Binary) AdminLogsUpload(w http.ResponseWriter, r *http.Request) {
	if b.identity == nil {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	id, ok, err := b.identity(r)
	if err != nil {
		b.log.Error("identity resolution unavailable", "err", err)
		w.Header().Set("Retry-After", "1")
		writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
		return
	}
	if !ok {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}

	body := map[string]any{"identity": id}
	if v := r.FormValue("tournament_id"); v != "" {
		body["tournament_id"] = v
	}
	if v := r.FormValue("encounter_id"); v != "" {
		body["encounter_id"] = v
	}

	encoded := []map[string]string{}
	if r.MultipartForm != nil {
		for _, fh := range r.MultipartForm.File["files[]"] {
			f, err := fh.Open()
			if err != nil {
				writeDetail(w, http.StatusBadRequest, "failed to read file")
				return
			}
			raw, err := io.ReadAll(io.LimitReader(f, maxUpload))
			_ = f.Close()
			if err != nil {
				writeDetail(w, http.StatusBadRequest, "failed to read file")
				return
			}
			encoded = append(encoded, map[string]string{
				"filename":    fh.Filename,
				"content_b64": base64.StdEncoding.EncodeToString(raw),
			})
		}
	}
	body["files"] = encoded

	b.relayJSON(w, r, "rpc.parser.logs.upload", body, http.StatusOK)
}

// TeamsBalancerUpload: POST /api/v1/teams/create/balancer. Multipart "file"
// (a balancer JSON export) -> base64; tournament_id arrives as a form field and
// payload_format as a query param.
func (b *Binary) TeamsBalancerUpload(w http.ResponseWriter, r *http.Request) {
	if b.identity == nil {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	id, ok, err := b.identity(r)
	if err != nil {
		b.log.Error("identity resolution unavailable", "err", err)
		w.Header().Set("Retry-After", "1")
		writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
		return
	}
	if !ok {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}
	body := map[string]any{"identity": id}
	if v := r.FormValue("tournament_id"); v != "" {
		body["tournament_id"] = v
	}
	if q := r.URL.Query(); len(q) > 0 {
		qm := map[string]any{}
		for k, vs := range q {
			if len(vs) > 0 {
				qm[k] = vs
			}
		}
		if len(qm) > 0 {
			body["query"] = qm
		}
	}
	if r.MultipartForm != nil {
		if files := r.MultipartForm.File["file"]; len(files) > 0 {
			f, err := files[0].Open()
			if err != nil {
				writeDetail(w, http.StatusBadRequest, "failed to read file")
				return
			}
			raw, err := io.ReadAll(io.LimitReader(f, maxUpload))
			_ = f.Close()
			if err != nil {
				writeDetail(w, http.StatusBadRequest, "failed to read file")
				return
			}
			body["content_b64"] = base64.StdEncoding.EncodeToString(raw)
		}
	}
	b.relayJSON(w, r, "rpc.parser.teams.create_balancer", body, http.StatusOK)
}

// relayJSON calls the RPC and relays the success envelope data as a JSON response.
func (b *Binary) relayJSON(w http.ResponseWriter, r *http.Request, queue string, data map[string]any, success int) {
	body, _ := json.Marshal(data)
	ctx, cancel := context.WithTimeout(r.Context(), binaryRPCTimeout)
	defer cancel()

	reply, err := b.rpc.Call(ctx, queue, body)
	if err != nil {
		if rpc.IsUnavailable(err) {
			b.log.Error("rpc unavailable", "queue", queue, "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return
		}
		b.log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(reply, &env); err != nil {
		b.log.Error("invalid rpc envelope", "queue", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return
	}
	if !env.OK {
		status := http.StatusInternalServerError
		msg := "internal error"
		if env.Error != nil {
			status = rpc.StatusForCode(env.Error.Code)
			msg = env.Error.Message
		}
		writeDetail(w, status, msg)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(success)
	// Relay a literal JSON `null` rather than an empty body (see edge/dispatch.go).
	if len(env.Data) > 0 {
		_, _ = w.Write(env.Data)
	}
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
