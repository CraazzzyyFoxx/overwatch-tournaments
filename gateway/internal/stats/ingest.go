package stats

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"mime"
	"net/http"
	"strings"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/upload"
)

const (
	// MaxIngestBody is the canonical-document cap. The backend enforces the same 25 MiB
	// (shared.schemas.match_doc.MAX_MATCH_DOC_BYTES) and nginx opens the same ceiling on the exact route.
	MaxIngestBody = 25 << 20

	ingestSubmitQueue = "rpc.stats.ingest.submit"
	ingestGetQueue    = "rpc.stats.ingest.get"
)

// Ingest is the dedicated raw-body relay for POST /api/v1/stats/matches. The generic edge.Dispatcher decodes the body
// into a Go map and re-marshals it, which would change the bytes the backend hashes for idempotency; this handler
// forwards the request bytes untouched next to the identity it resolved itself, so the body can never name one.
type Ingest struct {
	rpc      edge.RPCCaller
	identity edge.IdentityResolver
	log      *slog.Logger
}

// NewIngest builds the relay. identity must be non-nil: the route is authenticated.
func NewIngest(caller edge.RPCCaller, identity edge.IdentityResolver, log *slog.Logger) *Ingest {
	return &Ingest{rpc: caller, identity: identity, log: log}
}

// IngestRoutes are the JSON routes served by the generic dispatcher.
var IngestRoutes = []edge.RouteSpec{
	{Method: "GET", Pattern: "/api/v1/stats/ingest-jobs/{id}", Queue: ingestGetQueue, IDParam: "id", Auth: edge.AuthRequired},
}

// IngestDocRoutes lists the ingest routes for the OpenAPI spec. The POST is documentation-only (Ingest.Submit
// serves it): its request is the bare owt.match/1 document, never the private raw_base64 RPC request.
var IngestDocRoutes = append([]edge.RouteSpec{
	{Method: "POST", Pattern: "/api/v1/stats/matches", Queue: ingestSubmitQueue, Body: true, Auth: edge.AuthRequired, Success: http.StatusAccepted},
}, IngestRoutes...)

// Submit: POST /api/v1/stats/matches.
func (i *Ingest) Submit(w http.ResponseWriter, r *http.Request) {
	log := httplog.From(r.Context())
	id, ok, err := i.identity(r)
	if err != nil {
		log.Error("identity resolution unavailable", "err", err)
		w.Header().Set("Retry-After", "1")
		writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
		return
	}
	if !ok {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	if !isJSONContent(r.Header.Get("Content-Type")) {
		apierr.WriteError(w, http.StatusUnsupportedMediaType, "Content-Type must be application/json", "unsupported_media_type", nil)
		return
	}
	if r.ContentLength > MaxIngestBody {
		writeTooLarge(w)
		return
	}
	release, ok := upload.Admit(w, r, MaxIngestBody)
	if !ok {
		return
	}
	defer release()

	// One bounded buffer, sized from Content-Length when the client declared it.
	buf := bytes.NewBuffer(make([]byte, 0, max(r.ContentLength, 0)))
	if _, err := buf.ReadFrom(http.MaxBytesReader(w, r.Body, MaxIngestBody)); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writeTooLarge(w)
			return
		}
		apierr.WriteError(w, http.StatusBadRequest, "failed to read request body", "invalid_request", nil)
		return
	}

	body, err := ingestRPCBody(id, clientip.From(r), clientip.UserAgent(r), buf.Bytes())
	if err != nil {
		log.Error("ingest rpc body", "err", err)
		apierr.WriteError(w, http.StatusInternalServerError, "internal error", "internal", nil)
		return
	}
	i.relay(w, r, ingestSubmitQueue, body, submitStatus)
}

// ingestRPCBody builds {"identity","ip_address","raw_base64","user_agent"} in a single allocation: the original
// bytes are base64-encoded straight into the final message instead of via a string and a re-marshal.
func ingestRPCBody(identity map[string]any, ip, userAgent string, raw []byte) ([]byte, error) {
	fields := map[string]any{"identity": identity, "ip_address": ip, "user_agent": userAgent}
	return upload.Body(fields, "raw_base64", upload.Base64Len(int64(len(raw))), func(out []byte) ([]byte, error) {
		return upload.AppendBase64(out, bytes.NewReader(raw))
	})
}

// submitStatus: queued or running work is 202, any other actual state is 200.
func submitStatus(data []byte) int {
	var job struct {
		Status string `json:"status"`
	}
	if json.Unmarshal(data, &job) == nil && (job.Status == "pending" || job.Status == "processing") {
		return http.StatusAccepted
	}
	return http.StatusOK
}

func (i *Ingest) relay(w http.ResponseWriter, r *http.Request, queue string, body []byte, status func([]byte) int) {
	ctx, cancel := context.WithTimeout(r.Context(), binaryRPCTimeout)
	defer cancel()
	log := httplog.From(r.Context())

	reply, err := i.rpc.Call(ctx, queue, body)
	if err != nil {
		if rpc.IsUnavailable(err) {
			log.Error("rpc unavailable", "queue", queue, "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "service unavailable")
			return
		}
		if errors.Is(err, context.Canceled) {
			log.Info("rpc canceled by client", "queue", queue)
			return
		}
		log.Error("rpc failed", "queue", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "service timeout")
		return
	}
	var env rpc.Envelope
	if err := json.Unmarshal(reply, &env); err != nil {
		log.Error("invalid rpc envelope", "queue", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid service response")
		return
	}
	if !env.OK {
		apierr.WriteEnvelopeError(w, env.Error)
		return
	}
	apierr.WriteOK(w, status(env.Data), env)
}

func isJSONContent(header string) bool {
	media, _, err := mime.ParseMediaType(header)
	return err == nil && strings.EqualFold(media, "application/json")
}

func writeTooLarge(w http.ResponseWriter) {
	apierr.WriteError(w, http.StatusRequestEntityTooLarge, "document exceeds the maximum size", "match_document_too_large", nil)
}
