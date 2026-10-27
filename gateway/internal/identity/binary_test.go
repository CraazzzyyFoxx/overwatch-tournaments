package identity

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/upload"
)

func avatarRequest(t *testing.T, content string) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("file", "me <1>.png")
	_, _ = fw.Write([]byte(content))
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/auth/me/avatar", &buf)
	r.Header.Set("Content-Type", mw.FormDataContentType())
	r.Header.Set("Authorization", "Bearer acc<&>")
	return r
}

func avatarBinary(c *fakeCaller) *Binary {
	return NewBinary(newHandler(c), func(*http.Request) (map[string]any, bool, error) {
		return map[string]any{"user_id": float64(1)}, true, nil
	})
}

// The message used to be json.Marshal of the map holding an EncodeToString copy;
// it is now spliced together without it. The worker must see the same bytes.
func TestAvatarSetMessageIsByteIdenticalToTheOldEncoding(t *testing.T) {
	content := "\x89PNG\x00<&>" + strings.Repeat("a", 2048)
	c := &fakeCaller{resp: []byte(`{"ok":true,"data":{}}`)}
	w := httptest.NewRecorder()
	avatarBinary(c).AvatarSet(w, avatarRequest(t, content))
	if w.Code != http.StatusOK {
		t.Fatalf("code=%d body=%s", w.Code, w.Body)
	}

	want, _ := json.Marshal(map[string]any{
		"access_token": "acc<&>",
		"content_b64":  base64.StdEncoding.EncodeToString([]byte(content)),
		"content_type": "application/octet-stream",
		"filename":     "me <1>.png",
	})
	if !bytes.Equal(c.gotBody, want) {
		t.Fatalf("rpc body changed:\n got %.300s\nwant %.300s", c.gotBody, want)
	}
}

func TestAvatarSetIsShedWhenTheMemoryBudgetIsSpent(t *testing.T) {
	upload.SetMemoryBudget(1)
	t.Cleanup(func() { upload.SetMemoryBudget(0) })
	held, ok := upload.Admit(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/", strings.NewReader("x")), 1)
	if !ok {
		t.Fatal("could not occupy the budget")
	}
	defer held()

	c := &fakeCaller{resp: []byte(`{"ok":true,"data":{}}`)}
	w := httptest.NewRecorder()
	avatarBinary(c).AvatarSet(w, avatarRequest(t, "x"))
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" || c.called {
		t.Fatalf("code=%d retry-after=%q relayed=%v", w.Code, w.Header().Get("Retry-After"), c.called)
	}
}
