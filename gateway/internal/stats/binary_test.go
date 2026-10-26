package stats

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/upload"
)

func logsUploadRequest(t *testing.T, files map[string]string) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for _, name := range []string{"a <1>.log", "b.log"} {
		if content, ok := files[name]; ok {
			fw, _ := mw.CreateFormFile("files[]", name)
			_, _ = fw.Write([]byte(content))
		}
	}
	// Plain fields after the files: the multipart order must not matter.
	_ = mw.WriteField("tournament_id", "12")
	_ = mw.WriteField("encounter_id", "34")
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/admin/logs/upload", &buf)
	r.Header.Set("Content-Type", mw.FormDataContentType())
	return r
}

func logsBinary(f *fakeCaller) *Binary {
	identity := func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": 7, "roles": []any{"admin"}}, true, nil
	}
	return NewBinary(f, identity, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

// The message used to be json.Marshal of a map holding EncodeToString copies;
// it is now spliced together without them. The worker must see the same bytes.
func TestAdminLogsUploadMessageIsByteIdenticalToTheOldEncoding(t *testing.T) {
	files := map[string]string{"a <1>.log": "\x00\xffline1\n" + strings.Repeat("x", 5000), "b.log": "line2"}
	f := &fakeCaller{reply: envelope(`{}`)}
	w := httptest.NewRecorder()
	logsBinary(f).AdminLogsUpload(w, logsUploadRequest(t, files))
	if w.Code != http.StatusOK {
		t.Fatalf("code=%d body=%s", w.Code, w.Body)
	}

	want, _ := json.Marshal(map[string]any{
		"identity":      map[string]any{"user_id": 7, "roles": []any{"admin"}},
		"tournament_id": "12",
		"encounter_id":  "34",
		"files": []map[string]string{
			{"filename": "a <1>.log", "content_b64": base64.StdEncoding.EncodeToString([]byte(files["a <1>.log"]))},
			{"filename": "b.log", "content_b64": base64.StdEncoding.EncodeToString([]byte(files["b.log"]))},
		},
	})
	if !bytes.Equal(f.body, want) {
		t.Fatalf("rpc body changed:\n got %.300s\nwant %.300s", f.body, want)
	}

	// No files is still the empty list the worker always got.
	f = &fakeCaller{reply: envelope(`{}`)}
	logsBinary(f).AdminLogsUpload(httptest.NewRecorder(), logsUploadRequest(t, nil))
	if !bytes.Contains(f.body, []byte(`"files":[]`)) {
		t.Fatalf("empty upload: %s", f.body)
	}
}

// Admission runs before the body is parsed: with the budget held elsewhere the
// upload and the ingest are both shed with 503 + Retry-After, never relayed.
func TestUploadsAreShedWhenTheMemoryBudgetIsSpent(t *testing.T) {
	upload.SetMemoryBudget(1)
	t.Cleanup(func() { upload.SetMemoryBudget(0) })
	held, ok := upload.Admit(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/", strings.NewReader("x")), 1)
	if !ok {
		t.Fatal("could not occupy the budget")
	}
	defer held()

	f := &fakeCaller{reply: envelope(`{}`)}
	w := httptest.NewRecorder()
	logsBinary(f).AdminLogsUpload(w, logsUploadRequest(t, map[string]string{"b.log": "x"}))
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" || f.calls != 0 {
		t.Fatalf("logs upload: code=%d retry-after=%q calls=%d", w.Code, w.Header().Get("Retry-After"), f.calls)
	}

	w = post(ingestHandler(f, true, nil), "application/json", strings.NewReader("{}"))
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" || f.calls != 0 {
		t.Fatalf("ingest: code=%d retry-after=%q calls=%d", w.Code, w.Header().Get("Retry-After"), f.calls)
	}
}
