package stats

import (
	"context"
	"encoding/json"
	"log/slog"
	"mime/multipart"
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
	// stats-service's RequestSizeLimitMiddleware allows 50 MiB (log-file uploads).
	maxUpload = 50 << 20
)

// Binary serves the stats-service endpoints the generic JSON edge.Dispatcher
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
// each file into the RPC body for rpc.stats.logs.upload.
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
	release, ok := upload.Admit(w, r, maxUpload)
	if !ok {
		return
	}
	defer release()
	r.Body = http.MaxBytesReader(w, r.Body, maxUpload)
	if err := r.ParseMultipartForm(maxUpload); err != nil {
		writeDetail(w, http.StatusBadRequest, "invalid multipart form")
		return
	}

	fields := map[string]any{"identity": id}
	if v := r.FormValue("tournament_id"); v != "" {
		fields["tournament_id"] = v
	}
	if v := r.FormValue("encounter_id"); v != "" {
		fields["encounter_id"] = v
	}

	// "files" is [{"content_b64","filename"}, ...] (keys in json.Marshal order),
	// each file base64'd straight into the message.
	var files []*multipart.FileHeader
	if r.MultipartForm != nil {
		files = r.MultipartForm.File["files[]"]
	}
	size := 2
	for _, fh := range files {
		size += upload.Base64Len(fh.Size) + len(fh.Filename) + len(`{"content_b64":,"filename":""},`)
	}
	body, err := upload.Body(fields, "files", size, func(out []byte) ([]byte, error) {
		out = append(out, '[')
		for i, fh := range files {
			if i > 0 {
				out = append(out, ',')
			}
			f, err := fh.Open()
			if err != nil {
				return nil, err
			}
			out = append(out, `{"content_b64":`...)
			out, err = upload.AppendBase64(out, f)
			_ = f.Close()
			if err != nil {
				return nil, err
			}
			name, err := json.Marshal(fh.Filename)
			if err != nil {
				return nil, err
			}
			out = append(out, `,"filename":`...)
			out = append(out, name...)
			out = append(out, '}')
		}
		return append(out, ']'), nil
	})
	if err != nil {
		writeDetail(w, http.StatusBadRequest, "failed to read file")
		return
	}

	b.relayJSON(w, r, "rpc.stats.logs.upload", body, http.StatusOK)
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
