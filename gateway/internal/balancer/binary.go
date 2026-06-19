package balancer

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
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
	maxUpload        = 12 << 20 // 12 MiB upload cap before base64 into the RPC body
)

// Binary serves the balancer endpoint the generic JSON edge.Dispatcher can't:
// the teams-import multipart upload, base64-encoded into the RPC body. Permission
// is enforced in the worker; the gateway only injects the resolved identity.
type Binary struct {
	rpc      edge.RPCCaller
	identity edge.IdentityResolver
	log      *slog.Logger
}

// NewBinary builds the binary handler set. identity must be non-nil (the route is
// authenticated).
func NewBinary(caller edge.RPCCaller, identity edge.IdentityResolver, log *slog.Logger) *Binary {
	return &Binary{rpc: caller, identity: identity, log: log}
}

// TeamsImport: POST /api/balancer/balancer/tournaments/{tournament_id}/teams/import.
// Multipart: file part "data" (a JSON file) + optional form field "payload_format".
func (b *Binary) TeamsImport(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("tournament_id")})
	if !ok {
		return
	}
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}
	f, _, err := r.FormFile("data")
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "data file is required")
		return
	}
	defer func() { _ = f.Close() }()
	raw, err := io.ReadAll(io.LimitReader(f, maxUpload))
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return
	}
	data["content_b64"] = base64.StdEncoding.EncodeToString(raw)
	if pf := r.FormValue("payload_format"); pf != "" {
		data["payload_format"] = pf
	}
	b.relayJSON(w, r, "rpc.balancer.admin.teams_import", data, http.StatusOK)
}

// JobCreate: POST /api/balancer/jobs. Multipart: file part "player_data_file"
// (a JSON file) + optional form fields "config_overrides" and "tournament_id";
// query "workspace_id" is forwarded. Returns 202 (queued).
func (b *Binary) JobCreate(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{})
	if !ok {
		return
	}
	attachQuery(data, r) // forward workspace_id (and any other query param)
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}
	f, hdr, err := r.FormFile("player_data_file")
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "player_data_file is required")
		return
	}
	defer func() { _ = f.Close() }()
	raw, err := io.ReadAll(io.LimitReader(f, maxUpload))
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return
	}
	data["content_b64"] = base64.StdEncoding.EncodeToString(raw)
	data["content_type"] = hdr.Header.Get("Content-Type")
	data["filename"] = hdr.Filename
	if cfg := r.FormValue("config_overrides"); cfg != "" {
		data["config_overrides"] = cfg
	}
	if tid := r.FormValue("tournament_id"); tid != "" {
		data["tournament_id"] = tid
	}
	b.relayJSON(w, r, "rpc.balancer.jobs.create", data, http.StatusAccepted)
}

func attachQuery(data map[string]any, r *http.Request) {
	q := map[string]any{}
	for k, vs := range r.URL.Query() {
		if len(vs) > 0 {
			q[k] = vs
		}
	}
	if len(q) > 0 {
		data["query"] = q
	}
}

// identityInto resolves the bearer identity (required) and injects it into data.
func (b *Binary) identityInto(w http.ResponseWriter, r *http.Request, data map[string]any) (map[string]any, bool) {
	if b.identity == nil {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return nil, false
	}
	id, ok := b.identity(r)
	if !ok {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return nil, false
	}
	data["identity"] = id
	return data, true
}

// relayJSON calls the RPC and relays the success envelope data as a JSON response.
func (b *Binary) relayJSON(w http.ResponseWriter, r *http.Request, queue string, data map[string]any, success int) {
	body, _ := json.Marshal(data)
	ctx, cancel := context.WithTimeout(r.Context(), binaryRPCTimeout)
	defer cancel()

	reply, err := b.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			b.log.Error("rpc unavailable", "queue", queue, "err", err)
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
	if len(env.Data) > 0 && string(env.Data) != "null" {
		_, _ = w.Write(env.Data)
	}
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
