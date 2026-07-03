package identity

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	// avatarRPCTimeout covers the S3 round-trip inside identity-svc.
	avatarRPCTimeout = 30 * time.Second
	// maxAvatarUpload caps the multipart body before it is base64'd into the RPC
	// message. Avatars are small; identity-svc enforces the real 2 MiB limit.
	maxAvatarUpload = 12 << 20 // 12 MiB
)

const (
	queueAvatarSet    = "rpc.identity.me.avatar_set"
	queueAvatarDelete = "rpc.identity.me.avatar_delete"
)

// IdentityResolver validates a request's bearer token, returning the RBAC payload
// (or ok=false when absent/invalid). Matches principal.Resolver.Resolve.
type IdentityResolver func(r *http.Request) (map[string]any, bool)

// Binary serves the identity endpoint the JSON callIdentity path can't: the
// current-user avatar multipart upload, base64-encoded into the RPC body. Like
// the other authed identity routes, it forwards the bearer access_token (the
// worker resolves the active user from it via _with_active_user).
type Binary struct {
	*Handler
	resolver IdentityResolver
}

// NewBinary wraps the identity Handler for the avatar upload/delete routes. The
// resolver (may be nil) validates the bearer token BEFORE the multipart body is
// parsed, so an unauthenticated request is rejected without buffering the upload.
func NewBinary(h *Handler, resolver IdentityResolver) *Binary {
	return &Binary{Handler: h, resolver: resolver}
}

// AvatarSet: POST /api/auth/me/avatar. Multipart "file" -> base64 RPC body.
func (b *Binary) AvatarSet(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	// Validate the token up front (not just its presence) so an invalid bearer is
	// rejected before we buffer/parse the multipart upload.
	if b.resolver != nil {
		if _, ok := b.resolver(r); !ok {
			writeDetail(w, http.StatusUnauthorized, "Not authenticated")
			return
		}
	}
	// Cap the multipart body to bound memory/disk before parsing.
	r.Body = http.MaxBytesReader(w, r.Body, maxAvatarUpload)
	if err := r.ParseMultipartForm(maxAvatarUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "file is required")
		return
	}
	defer func() { _ = f.Close() }()
	raw, err := io.ReadAll(io.LimitReader(f, maxAvatarUpload))
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return
	}
	ct := hdr.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/octet-stream"
	}
	body, _ := json.Marshal(map[string]any{
		"access_token": token,
		"content_b64":  base64.StdEncoding.EncodeToString(raw),
		"content_type": ct,
		"filename":     hdr.Filename,
	})
	b.relayAvatar(w, r, queueAvatarSet, body)
}

// AvatarDelete: DELETE /api/auth/me/avatar.
func (b *Binary) AvatarDelete(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token})
	b.relayAvatar(w, r, queueAvatarDelete, body)
}

// relayAvatar calls the RPC (with the longer S3-aware timeout) and relays the
// success-envelope data as a 200 JSON response, mirroring callIdentity's error map.
func (b *Binary) relayAvatar(w http.ResponseWriter, r *http.Request, queue string, body []byte) {
	ctx, cancel := context.WithTimeout(r.Context(), avatarRPCTimeout)
	defer cancel()

	raw, err := b.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			b.log.Error("identity rpc unavailable", "method", queue, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "identity service unavailable")
			return
		}
		b.log.Error("identity rpc failed", "method", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "identity service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		b.log.Error("invalid rpc envelope", "method", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid identity response")
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
	w.WriteHeader(http.StatusOK)
	// Relay a literal JSON `null` rather than an empty body (see edge/dispatch.go).
	if len(env.Data) > 0 {
		_, _ = w.Write(env.Data)
	}
}
