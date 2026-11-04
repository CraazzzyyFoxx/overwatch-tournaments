package balancer

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The source's body is not JSON the dispatcher accepts (a bare number is fine for the source, a 400 for the
// dispatcher), so the raw bytes and the secret header must reach the worker untouched.
func TestLobbyCallbackRelaysTheRawBodyAndSecretAndAnswers204(t *testing.T) {
	c := &recordingCaller{}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/deadlock/lobby-callback/tok", strings.NewReader("123456789"))
	r.SetPathValue("token", "tok")
	r.Header.Set("X-Callback-Secret", "s3cret")
	w := httptest.NewRecorder()
	jobBinary(c).LobbyCallback(w, r)

	if w.Code != http.StatusNoContent {
		t.Fatalf("code=%d body=%s", w.Code, w.Body)
	}
	var got map[string]string
	if err := json.Unmarshal(c.body, &got); err != nil {
		t.Fatal(err)
	}
	if got["token"] != "tok" || got["body"] != "123456789" || got["secret"] != "s3cret" {
		t.Fatalf("rpc body = %s", c.body)
	}
}

func TestLobbyCallbackRefusesAnOversizedBodyWithoutCallingTheWorker(t *testing.T) {
	c := &recordingCaller{}
	r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(strings.Repeat("1", callbackBodyLimit+1)))
	w := httptest.NewRecorder()
	jobBinary(c).LobbyCallback(w, r)
	if w.Code != http.StatusRequestEntityTooLarge || c.body != nil {
		t.Fatalf("code=%d relayed=%v", w.Code, c.body != nil)
	}
}

func TestLobbyCallbackSettingsIsAcknowledgedAtTheEdge(t *testing.T) {
	c := &recordingCaller{}
	w := httptest.NewRecorder()
	jobBinary(c).LobbyCallbackSettings(w, httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"a":1}`)))
	if w.Code != http.StatusNoContent || c.body != nil {
		t.Fatalf("code=%d relayed=%v", w.Code, c.body != nil)
	}
}
