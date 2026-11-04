package balancer

import (
	"encoding/json"
	"io"
	"net/http"
)

// callbackBodyLimit bounds what a game source may POST to a bot-lobby callback: a match id is a few digits.
const callbackBodyLimit = 16 << 10

// LobbyCallback: POST /api/v1/deadlock/lobby-callback/{token}. The game source reports the match id of a bot-created
// lobby here. Public (the one-time token in the path is the credential, checked by the worker) and not a JSON
// route: the source's body format is its own (a bare number, a string, an object, or plain digits) and its secret
// arrives in X-Callback-Secret, neither of which the generic dispatcher relays. The raw body and the header go to
// the worker verbatim, which answers 204 for every token.
func (b *Binary) LobbyCallback(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, callbackBodyLimit))
	if err != nil {
		writeDetail(w, http.StatusRequestEntityTooLarge, "Request body too large")
		return
	}
	body, _ := json.Marshal(map[string]any{
		"token":  r.PathValue("token"),
		"body":   string(raw),
		"secret": r.Header.Get("X-Callback-Secret"),
	})
	b.relayJSON(w, r, "rpc.balancer.custom.bot_lobby_callback", body, http.StatusNoContent)
}

// LobbyCallbackSettings: POST /api/v1/deadlock/lobby-callback/{token}/settings. The source reports the party's
// settings changes here; nothing reads them, so they are acknowledged without a worker round trip.
func (b *Binary) LobbyCallbackSettings(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusNoContent)
}
