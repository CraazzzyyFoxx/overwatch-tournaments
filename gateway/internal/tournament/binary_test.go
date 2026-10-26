package tournament

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

func imageUploadRequest(t *testing.T, content string) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("file", "cover.png")
	_, _ = fw.Write([]byte(content))
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/admin/tournaments/4/images/cover", &buf)
	r.Header.Set("Content-Type", mw.FormDataContentType())
	r.SetPathValue("tournament_id", "4")
	r.SetPathValue("slot", "cover")
	return r
}

func imageBinary(c *capturingCaller) *Binary {
	identity := func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": float64(8)}, true, nil
	}
	return NewBinary(c, identity, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

// The message used to be json.Marshal of the map holding an EncodeToString copy;
// it is now spliced together without it. The worker must see the same bytes.
func TestTournamentImageUploadMessageIsByteIdenticalToTheOldEncoding(t *testing.T) {
	content := "\x89PNG\x00<&>" + strings.Repeat("i", 2048)
	c := &capturingCaller{}
	w := httptest.NewRecorder()
	imageBinary(c).TournamentImageUpload(w, imageUploadRequest(t, content))
	if w.Code != http.StatusOK {
		t.Fatalf("code=%d body=%s", w.Code, w.Body)
	}

	want, _ := json.Marshal(map[string]any{
		"id":           "4",
		"slot":         "cover",
		"identity":     map[string]any{"user_id": float64(8)},
		"content_b64":  base64.StdEncoding.EncodeToString([]byte(content)),
		"content_type": "application/octet-stream",
	})
	if !bytes.Equal(c.body, want) {
		t.Fatalf("rpc body changed:\n got %.300s\nwant %.300s", c.body, want)
	}
}

func TestTournamentImageUploadIsShedWhenTheMemoryBudgetIsSpent(t *testing.T) {
	upload.SetMemoryBudget(1)
	t.Cleanup(func() { upload.SetMemoryBudget(0) })
	held, ok := upload.Admit(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/", strings.NewReader("x")), 1)
	if !ok {
		t.Fatal("could not occupy the budget")
	}
	defer held()

	c := &capturingCaller{}
	w := httptest.NewRecorder()
	imageBinary(c).TournamentImageUpload(w, imageUploadRequest(t, "x"))
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" || c.body != nil {
		t.Fatalf("code=%d retry-after=%q relayed=%v", w.Code, w.Header().Get("Retry-After"), c.body != nil)
	}
}
