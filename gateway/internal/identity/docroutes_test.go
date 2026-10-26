package identity

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// The bespoke handlers write their own success status; the doc tables are a
// hand-kept mirror. These routes were documented as 200-with-JSON while the
// handler answered 204 (or 201), so generated clients expected a body that
// never comes. Each case runs the real handler and compares.
func TestBespokeSuccessStatusesMatchTheDocs(t *testing.T) {
	h := newHandler(&fakeCaller{resp: []byte(`{"ok":true,"data":{}}`)})
	served := map[string]http.HandlerFunc{
		queueLogout:                 h.Logout,
		queueLogoutAll:              h.LogoutAll,
		queueSetPassword:            h.SetPassword,
		queueInvalidateSession:      h.InvalidateSession,
		queueRbacAssignRole:         h.RbacAssignRole,
		queueRbacRemoveRole:         h.RbacRemoveRole,
		queueRbacAssignLinkedPlayer: h.RbacAssignLinkedPlayer,
		queuePlayerLink:             h.PlayerLink,
	}
	docs := append(append([]edge.RouteSpec(nil), PublicDocRoutes...), AdminDocRoutes...)
	for queue, handler := range served {
		var documented int
		for _, route := range docs {
			if route.Queue == queue {
				documented = route.Success
			}
		}
		if documented == 0 {
			documented = http.StatusOK
		}

		r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"refresh_token":"rt"}`))
		r.Header.Set("Authorization", "Bearer acc")
		r.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		handler(w, r)
		if w.Code != documented {
			t.Errorf("%s: handler answers %d, docs say %d", queue, w.Code, documented)
		}
	}
}
