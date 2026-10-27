package app

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/upload"
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
	// download resolves the credential for routes a browser NAVIGATES to (the
	// match-log link), where an Authorization header cannot be attached — see
	// principal.Resolver.ResolveWithSessionCookie. Falls back to identity when
	// nil so a caller that does not serve downloads need not supply it.
	download edge.IdentityResolver
	log      *slog.Logger
}

// NewBinary builds the binary handler set. identity must be non-nil for the
// authenticated upload/delete routes; download additionally accepts the session
// cookie and backs the match-log read (nil reuses identity, which then rejects
// every browser-navigated download).
func NewBinary(caller edge.RPCCaller, identity, download edge.IdentityResolver, log *slog.Logger) *Binary {
	if download == nil {
		download = identity
	}
	return &Binary{rpc: caller, identity: identity, download: download, log: log}
}

// IconUpload: POST /api/v1/workspaces/{id}/icon (workspace.update in worker).
func (b *Binary) IconUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	body, release, ok := b.fileBody(w, r, id)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.app.workspaces.icon_upload", body, http.StatusOK)
}

// IconDelete: DELETE /api/v1/workspaces/{id}/icon (workspace.update in worker).
func (b *Binary) IconDelete(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	body, _ := json.Marshal(id)
	b.relayJSON(w, r, "rpc.app.workspaces.icon_delete", body, http.StatusOK)
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
	body, release, ok := b.fileBody(w, r, data)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.app.assets.upload", body, http.StatusOK)
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
	body, _ := json.Marshal(data)
	b.relayJSON(w, r, "rpc.app.assets.delete", body, http.StatusOK)
}

// MatchLog: GET /api/v1/matches/{match_id}/log. Returns the raw log bytes
// decoded from the worker's base64 payload.
//
// Authenticated, like every other route in this file — the declared contract
// (docroutes.go) always said so while the handler read no credential at all.
// The credential resolves through b.download rather than b.identity because the
// frontend exposes this as an `<a download>` link the BROWSER navigates to, so
// the session cookie is the only thing the request carries.
func (b *Binary) MatchLog(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityFrom(w, r, b.download, map[string]any{"id": r.PathValue("match_id")})
	if !ok {
		return
	}
	body, _ := json.Marshal(data)
	env, ok := b.invoke(w, r, "rpc.app.matches.log", body)
	if !ok {
		return
	}
	raw := env.Data
	var payload struct {
		ContentB64 string `json:"content_b64"`
		MediaType  string `json:"media_type"`
		Filename   string `json:"filename"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return
	}
	logBytes, err := base64.StdEncoding.DecodeString(payload.ContentB64)
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
	_, _ = w.Write(logBytes)
}

// UserAvatarUpload: POST /api/v1/admin/users/{id}/avatar (user.update in worker).
// Relocated from parser; multipart "file" -> base64 RPC body.
func (b *Binary) UserAvatarUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("id")})
	if !ok {
		return
	}
	body, release, ok := b.fileBody(w, r, id)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.app.users.avatar_upload", body, http.StatusOK)
}

// identityInto resolves the bearer identity (required) and injects it into data.
// Returns ok=false (and writes 401) when no valid identity is present.
func (b *Binary) identityInto(w http.ResponseWriter, r *http.Request, data map[string]any) (map[string]any, bool) {
	return b.identityFrom(w, r, b.identity, data)
}

// identityFrom is identityInto against an explicit resolver, so a route whose
// credential arrives somewhere else (the match-log download, see b.download)
// shares the identical 401/503 handling instead of reimplementing it.
func (b *Binary) identityFrom(
	w http.ResponseWriter,
	r *http.Request,
	resolve edge.IdentityResolver,
	data map[string]any,
) (map[string]any, bool) {
	if resolve == nil {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return nil, false
	}
	id, ok, err := resolve(r)
	if err != nil {
		b.log.Error("identity resolution unavailable", "err", err)
		w.Header().Set("Retry-After", "1")
		writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
		return nil, false
	}
	if !ok {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return nil, false
	}
	data["identity"] = id
	return data, true
}

// fileBody admits the upload against the gateway's memory budget, parses the
// multipart "file" part and returns the RPC message: data plus content_type and
// content_b64, the file base64'd straight into the message. On success the
// caller must defer release, which frees the reservation once the RPC is done.
func (b *Binary) fileBody(w http.ResponseWriter, r *http.Request, data map[string]any) (body []byte, release func(), ok bool) {
	rel, admitted := upload.Admit(w, r, maxUpload)
	if !admitted {
		return nil, nil, false
	}
	defer func() {
		if !ok {
			rel()
		}
	}()
	r.Body = http.MaxBytesReader(w, r.Body, maxUpload)
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return nil, nil, false
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "file is required")
		return nil, nil, false
	}
	defer func() { _ = f.Close() }()
	data["content_type"] = hdr.Header.Get("Content-Type")
	body, err = upload.Body(data, "content_b64", upload.Base64Len(hdr.Size), func(out []byte) ([]byte, error) {
		return upload.AppendBase64(out, f)
	})
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return nil, nil, false
	}
	return body, rel, true
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

func (b *Binary) relayJSON(w http.ResponseWriter, r *http.Request, queue string, body []byte, success int) {
	env, ok := b.invoke(w, r, queue, body)
	if !ok {
		return
	}
	apierr.WriteOK(w, success, env)
}

func (b *Binary) invoke(w http.ResponseWriter, r *http.Request, queue string, body []byte) (rpc.Envelope, bool) {
	ctx, cancel := context.WithTimeout(r.Context(), binaryRPCTimeout)
	defer cancel()

	reply, err := b.rpc.Call(ctx, queue, body)
	if err != nil {
		if rpc.IsUnavailable(err) {
			b.log.Error("rpc unavailable", "queue", queue, "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return rpc.Envelope{}, false
		}
		b.log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return rpc.Envelope{}, false
	}

	var env rpc.Envelope
	if err := json.Unmarshal(reply, &env); err != nil {
		b.log.Error("invalid rpc envelope", "queue", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return rpc.Envelope{}, false
	}
	if !env.OK {
		apierr.WriteEnvelopeError(w, env.Error)
		return rpc.Envelope{}, false
	}
	return env, true
}

// writeDetail emits the gateway's error body for this handler's OWN failures;
// upstream envelope errors go through apierr.WriteEnvelopeError so their code,
// structured details and Retry-After survive.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	apierr.WriteError(w, status, detail, "", nil)
}
