package app

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

// Binary serves the app-service endpoints the generic JSON edge.Dispatcher can't:
// multipart uploads (base64-encoded into the RPC body) and the match-log download
// (base64 out -> raw bytes). Permission is enforced in the worker; the gateway only
// injects identity (resolved here) for the authenticated routes.
type Binary struct {
	rpc      edge.RPCCaller
	identity edge.IdentityResolver
	log      *slog.Logger
}

// NewBinary builds the binary handler set. identity must be non-nil for the
// authenticated upload/delete routes; the match-log read is public.
func NewBinary(caller edge.RPCCaller, identity edge.IdentityResolver, log *slog.Logger) *Binary {
	return &Binary{rpc: caller, identity: identity, log: log}
}

// IconUpload: POST /api/v1/workspaces/{id}/icon (workspace.update in worker).
func (b *Binary) IconUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	if !b.attachFile(w, r, id) {
		return
	}
	b.relayJSON(w, r, "rpc.app.workspaces.icon_upload", id, http.StatusOK)
}

// IconDelete: DELETE /api/v1/workspaces/{id}/icon (workspace.update in worker).
func (b *Binary) IconDelete(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	b.relayJSON(w, r, "rpc.app.workspaces.icon_delete", id, http.StatusOK)
}

// AssetUpload: POST /api/v1/assets/{asset_type}/{slug} (superuser in worker).
func (b *Binary) AssetUpload(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{
		"asset_type": r.PathValue("asset_type"),
		"slug":       r.PathValue("slug"),
	})
	if !ok {
		return
	}
	attachQuery(data, r)
	if !b.attachFile(w, r, data) {
		return
	}
	b.relayJSON(w, r, "rpc.app.assets.upload", data, http.StatusOK)
}

// AssetDelete: DELETE /api/v1/assets/{asset_type}/{slug} (superuser in worker).
func (b *Binary) AssetDelete(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{
		"asset_type": r.PathValue("asset_type"),
		"slug":       r.PathValue("slug"),
	})
	if !ok {
		return
	}
	attachQuery(data, r)
	b.relayJSON(w, r, "rpc.app.assets.delete", data, http.StatusOK)
}

// MatchLog: GET /api/v1/matches/{match_id}/log (public). Returns the raw log
// bytes decoded from the worker's base64 payload.
func (b *Binary) MatchLog(w http.ResponseWriter, r *http.Request) {
	data := map[string]any{"id": r.PathValue("match_id")}
	raw, ok := b.invoke(w, r, "rpc.app.matches.log", data)
	if !ok {
		return
	}
	var payload struct {
		ContentB64 string `json:"content_b64"`
		MediaType  string `json:"media_type"`
		Filename   string `json:"filename"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return
	}
	body, err := base64.StdEncoding.DecodeString(payload.ContentB64)
	if err != nil {
		writeDetail(w, http.StatusBadGateway, "invalid log payload")
		return
	}
	ct := payload.MediaType
	if ct == "" {
		ct = "application/octet-stream"
	}
	w.Header().Set("Content-Type", ct)
	if payload.Filename != "" {
		w.Header().Set("Content-Disposition", `attachment; filename="`+payload.Filename+`"`)
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

// UserAvatarUpload: POST /api/v1/admin/users/{id}/avatar (user.update in worker).
// Relocated from parser; multipart "file" -> base64 RPC body.
func (b *Binary) UserAvatarUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	if !b.attachFile(w, r, id) {
		return
	}
	b.relayJSON(w, r, "rpc.app.users.avatar_upload", id, http.StatusOK)
}

// UsersCsvImport: POST /api/v1/user/create/csv (admin role in worker).
// Relocated from parser. Row indices + delimiter + flags + an optional Google
// Sheets URL arrive as query params; an optional CSV file rides in the multipart
// "data" field (base64 into the RPC body). The worker handles file-vs-sheet.
func (b *Binary) UsersCsvImport(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{})
	if !ok {
		return
	}
	attachQuery(data, r)
	if err := r.ParseMultipartForm(maxUpload); err == nil && r.MultipartForm != nil {
		if files := r.MultipartForm.File["data"]; len(files) > 0 {
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
			data["content_b64"] = base64.StdEncoding.EncodeToString(raw)
			data["filename"] = files[0].Filename
		}
	}
	b.relayJSON(w, r, "rpc.app.users.csv_import", data, http.StatusOK)
}

// identityInto resolves the bearer identity (required) and injects it into data.
// Returns ok=false (and writes 401) when no valid identity is present.
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

// attachFile parses the multipart "file" part and base64-encodes it into data.
func (b *Binary) attachFile(w http.ResponseWriter, r *http.Request, data map[string]any) bool {
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return false
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "file is required")
		return false
	}
	defer func() { _ = f.Close() }()
	raw, err := io.ReadAll(io.LimitReader(f, maxUpload))
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return false
	}
	data["content_b64"] = base64.StdEncoding.EncodeToString(raw)
	data["content_type"] = hdr.Header.Get("Content-Type")
	return true
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

// relayJSON calls the RPC and relays the success envelope data as a JSON response.
func (b *Binary) relayJSON(w http.ResponseWriter, r *http.Request, queue string, data map[string]any, success int) {
	raw, ok := b.invoke(w, r, queue, data)
	if !ok {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(success)
	if len(raw) > 0 && string(raw) != "null" {
		_, _ = w.Write(raw)
	}
}

// invoke marshals data, performs the RPC, and maps the {ok,data,error} envelope.
// On any failure it writes the HTTP error and returns ok=false.
func (b *Binary) invoke(w http.ResponseWriter, r *http.Request, queue string, data map[string]any) (json.RawMessage, bool) {
	body, _ := json.Marshal(data)
	ctx, cancel := context.WithTimeout(r.Context(), binaryRPCTimeout)
	defer cancel()

	reply, err := b.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			b.log.Error("rpc unavailable", "queue", queue, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return nil, false
		}
		b.log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return nil, false
	}

	var env rpc.Envelope
	if err := json.Unmarshal(reply, &env); err != nil {
		b.log.Error("invalid rpc envelope", "queue", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return nil, false
	}
	if !env.OK {
		status := http.StatusInternalServerError
		msg := "internal error"
		if env.Error != nil {
			status = rpc.StatusForCode(env.Error.Code)
			msg = env.Error.Message
		}
		writeDetail(w, status, msg)
		return nil, false
	}
	return env.Data, true
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
