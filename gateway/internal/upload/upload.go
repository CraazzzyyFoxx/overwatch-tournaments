// Package upload bounds the memory the gateway spends on request bodies it has
// to hold whole — the multipart uploads and the match-ingest document — and
// builds their RPC messages without intermediate copies.
//
// Each such body is base64'd into one AMQP message, so a request costs a
// multiple of its size, and the per-queue RPC bulkhead only engages AFTER the
// body has been parsed. Admit therefore runs before the body is read, against
// one process-wide byte budget, and sheds the request with an immediate 503
// once that budget is spent, instead of letting concurrent uploads grow the
// heap toward the container limit.
package upload

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
)

// PeakFactor is the multiple of its body size one request holds at its peak:
// up to 2x for the multipart buffer (mime/multipart reads each file into a
// bytes.Buffer whose doubling growth can leave the backing array at twice the
// file), 4/3x for the base64 RPC message Body builds, and the rest for growth
// garbage the GC has not reclaimed yet. The ingest relay needs less (1x raw +
// 4/3x message); one conservative factor keeps the accounting simple.
const PeakFactor = 4

// retryAfter is seconds, not the usual 1: the budget frees when an in-flight
// upload's RPC returns, which takes seconds for a multi-megabyte body.
const retryAfter = "5"

var budget struct {
	sync.Mutex
	limit int64 // 0 = unlimited
	used  int64
}

// SetMemoryBudget sets the process-wide byte budget (config.UploadMemoryBudget).
// Call once at startup; 0 (the zero value) means unlimited.
func SetMemoryBudget(bytes int64) {
	budget.Lock()
	budget.limit = bytes
	budget.Unlock()
}

// Admit reserves this request's share of the budget before its body is read:
// PeakFactor times min(Content-Length, maxBody), or maxBody when the length is
// unknown. The server never reads past a declared Content-Length, so it is a
// safe bound. On refusal it writes 503 + Retry-After and returns ok=false;
// otherwise the caller must call release once the body and the RPC message
// built from it are dead (after the RPC returns — defer it in the handler).
//
// Run it after authentication, so anonymous requests cannot spend the budget.
func Admit(w http.ResponseWriter, r *http.Request, maxBody int64) (release func(), ok bool) {
	n := maxBody
	if r.ContentLength >= 0 && r.ContentLength < n {
		n = r.ContentLength
	}
	n *= PeakFactor

	budget.Lock()
	if budget.limit > 0 {
		// Clamped so a lone upload bigger than the whole budget (a 50 MiB log
		// under a small dev budget) still runs when nothing else is in flight,
		// rather than being refused forever.
		n = min(n, budget.limit)
		if budget.used+n > budget.limit {
			budget.Unlock()
			w.Header().Set("Retry-After", retryAfter)
			apierr.WriteError(w, http.StatusServiceUnavailable, "upload capacity exhausted, retry shortly", "unavailable", nil)
			return nil, false
		}
	}
	budget.used += n
	budget.Unlock()

	return sync.OnceFunc(func() {
		budget.Lock()
		budget.used -= n
		budget.Unlock()
	}), true
}

// Body returns exactly json.Marshal(fields) plus one more member, key, whose
// raw JSON value put appends. A multi-megabyte base64 string is thus written
// once, straight into the final message, instead of via a string, a map and a
// re-marshal. size is put's expected output length, so the message is
// allocated once. fields must not contain key.
//
// It works because json.Marshal writes map members sorted by key: the members
// below key, the new member, then the members above it is the same byte string.
func Body(fields map[string]any, key string, size int, put func([]byte) ([]byte, error)) ([]byte, error) {
	lo := make(map[string]any, len(fields))
	hi := make(map[string]any, len(fields))
	for k, v := range fields {
		if k < key {
			lo[k] = v
		} else {
			hi[k] = v
		}
	}
	head, err := json.Marshal(lo)
	if err != nil {
		return nil, err
	}
	tail, err := json.Marshal(hi)
	if err != nil {
		return nil, err
	}
	name, err := json.Marshal(key)
	if err != nil {
		return nil, err
	}

	out := make([]byte, 0, len(head)+len(name)+size+len(tail)+1)
	out = append(out, head[:len(head)-1]...) // without the closing '}'
	if len(lo) > 0 {
		out = append(out, ',')
	}
	out = append(out, name...)
	out = append(out, ':')
	if out, err = put(out); err != nil {
		return nil, err
	}
	if len(hi) == 0 {
		return append(out, '}'), nil
	}
	out = append(out, ',')
	return append(out, tail[1:]...), nil // without the opening '{'
}

// Base64Len is the length AppendBase64 adds for n source bytes.
func Base64Len(n int64) int {
	return base64.StdEncoding.EncodedLen(int(n)) + 2
}

// AppendBase64 appends src's padded standard base64 (what EncodeToString
// returns) as a JSON string, streaming src so its bytes are never copied whole.
// The base64 alphabet needs no JSON escaping.
func AppendBase64(dst []byte, src io.Reader) ([]byte, error) {
	a := appender(append(dst, '"'))
	enc := base64.NewEncoder(base64.StdEncoding, &a)
	if _, err := io.Copy(enc, src); err != nil {
		return nil, err
	}
	if err := enc.Close(); err != nil {
		return nil, err
	}
	return append(a, '"'), nil
}

type appender []byte

func (a *appender) Write(p []byte) (int, error) {
	*a = append(*a, p...)
	return len(p), nil
}
