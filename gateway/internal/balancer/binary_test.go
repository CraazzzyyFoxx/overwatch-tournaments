package balancer

import (
	"bytes"
	"context"
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

type recordingCaller struct{ body []byte }

func (c *recordingCaller) Call(_ context.Context, _ string, body []byte) ([]byte, error) {
	c.body = body
	return []byte(`{"ok":true,"data":{"id":"job"}}`), nil
}

func jobCreateRequest(t *testing.T, content string) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("player_data_file", "players <1>.json")
	_, _ = fw.Write([]byte(content))
	// Plain fields after the file: the multipart order must not matter.
	_ = mw.WriteField("config_overrides", `{"x":"<&>"}`)
	_ = mw.WriteField("tournament_id", "9")
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/balancer/jobs?workspace_id=3", &buf)
	r.Header.Set("Content-Type", mw.FormDataContentType())
	return r
}

func jobBinary(c *recordingCaller) *Binary {
	identity := func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": float64(5)}, true, nil
	}
	return NewBinary(c, identity, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

// The message used to be json.Marshal of the map holding an EncodeToString copy;
// it is now spliced together without it. The worker must see the same bytes.
func TestJobCreateMessageIsByteIdenticalToTheOldEncoding(t *testing.T) {
	content := `[{"name":"<p&1>"}]` + strings.Repeat(" ", 3000)
	c := &recordingCaller{}
	w := httptest.NewRecorder()
	jobBinary(c).JobCreate(w, jobCreateRequest(t, content))
	if w.Code != http.StatusAccepted {
		t.Fatalf("code=%d body=%s", w.Code, w.Body)
	}

	want, _ := json.Marshal(map[string]any{
		"identity":         map[string]any{"user_id": float64(5)},
		"query":            map[string]any{"workspace_id": []string{"3"}},
		"content_b64":      base64.StdEncoding.EncodeToString([]byte(content)),
		"content_type":     "application/octet-stream",
		"filename":         "players <1>.json",
		"config_overrides": `{"x":"<&>"}`,
		"tournament_id":    "9",
	})
	if !bytes.Equal(c.body, want) {
		t.Fatalf("rpc body changed:\n got %.300s\nwant %.300s", c.body, want)
	}
}

func TestJobCreateIsShedWhenTheMemoryBudgetIsSpent(t *testing.T) {
	upload.SetMemoryBudget(1)
	t.Cleanup(func() { upload.SetMemoryBudget(0) })
	held, ok := upload.Admit(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/", strings.NewReader("x")), 1)
	if !ok {
		t.Fatal("could not occupy the budget")
	}
	defer held()

	c := &recordingCaller{}
	w := httptest.NewRecorder()
	jobBinary(c).JobCreate(w, jobCreateRequest(t, "[]"))
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" || c.body != nil {
		t.Fatalf("code=%d retry-after=%q relayed=%v", w.Code, w.Header().Get("Retry-After"), c.body != nil)
	}
}
