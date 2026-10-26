package tournament

import (
	"context"
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

// Binary serves the tournament-service endpoints the generic JSON edge.Dispatcher
// can't: the multipart image uploads, base64-encoded into the RPC body — the
// admin team logo, the captain-owned registered-team crest and the admin
// tournament cover/logo. Every paired delete is plain JSON and rides the typed
// dispatcher (admin_routes.go / public_routes.go). Permission is enforced in the
// worker; the gateway only injects the resolved identity.
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

// TeamImageUpload: POST /api/v1/admin/teams/{team_id}/image (team.update in the
// worker). Multipart "file" -> base64 RPC body, same shape as the user-avatar
// upload in internal/app.
func (b *Binary) TeamImageUpload(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("team_id")})
	if !ok {
		return
	}
	body, release, ok := b.fileBody(w, r, data)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.tournament.teams.image_upload", body, http.StatusOK)
}

// RegistrationTeamImageUpload: POST /api/v1/registration-teams/{team_id}/image
// (captain-gated in the worker, not workspace-permission-gated). The id travels
// as "team_id" — the key the regteam_* subjects read — not TeamImageUpload's "id".
func (b *Binary) RegistrationTeamImageUpload(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{"team_id": r.PathValue("team_id")})
	if !ok {
		return
	}
	body, release, ok := b.fileBody(w, r, data)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.tournament.regteam_image_upload", body, http.StatusOK)
}

// TournamentImageUpload: POST /api/v1/admin/tournaments/{tournament_id}/images/{slot}
// (tournament.update in the worker). Unlike its siblings the target picture also
// travels in the path: {slot} is "cover" or "logo", relayed verbatim so the
// worker owns both the permission check and the slot validation — the gateway
// never has to learn which slots exist.
func (b *Binary) TournamentImageUpload(w http.ResponseWriter, r *http.Request) {
	data, ok := b.identityInto(w, r, map[string]any{"id": r.PathValue("tournament_id"), "slot": r.PathValue("slot")})
	if !ok {
		return
	}
	body, release, ok := b.fileBody(w, r, data)
	if !ok {
		return
	}
	defer release()
	b.relayJSON(w, r, "rpc.tournament.tournaments.image_upload", body, http.StatusOK)
}

// identityInto resolves the bearer identity (required) and injects it into data.
// Returns ok=false (and writes 401) when no valid identity is present.
func (b *Binary) identityInto(w http.ResponseWriter, r *http.Request, data map[string]any) (map[string]any, bool) {
	if b.identity == nil {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return nil, false
	}
	id, ok, err := b.identity(r)
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

// relayJSON calls the RPC and relays the success envelope data as a JSON response.
func (b *Binary) relayJSON(w http.ResponseWriter, r *http.Request, queue string, body []byte, success int) {
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
		apierr.WriteEnvelopeError(w, env.Error)
		return
	}
	apierr.WriteOK(w, success, env)
}

// writeDetail emits the gateway's error body for this handler's OWN failures;
// upstream envelope errors go through apierr.WriteEnvelopeError so their code,
// structured details and Retry-After survive.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	apierr.WriteError(w, status, detail, "", nil)
}
