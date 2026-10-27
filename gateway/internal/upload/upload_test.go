package upload

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func setBudget(t *testing.T, bytes int64) {
	t.Helper()
	SetMemoryBudget(bytes)
	t.Cleanup(func() { SetMemoryBudget(0) })
}

func requestOf(n int) *http.Request {
	return httptest.NewRequest(http.MethodPost, "/upload", strings.NewReader(strings.Repeat("x", n)))
}

func TestAdmitRefusesOnceTheBudgetIsSpentAndReadmitsAfterRelease(t *testing.T) {
	setBudget(t, 10*PeakFactor)

	first, ok := Admit(httptest.NewRecorder(), requestOf(6), 1<<20)
	if !ok {
		t.Fatal("first upload refused under an empty budget")
	}

	w := httptest.NewRecorder()
	if _, ok := Admit(w, requestOf(6), 1<<20); ok {
		t.Fatal("second upload admitted past the budget")
	}
	if w.Code != http.StatusServiceUnavailable || w.Header().Get("Retry-After") == "" {
		t.Fatalf("refusal: code=%d retry-after=%q", w.Code, w.Header().Get("Retry-After"))
	}
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["code"] != "unavailable" {
		t.Fatalf("refusal body: %s", w.Body)
	}

	first()
	first() // idempotent: a double release must not mint budget
	again, ok := Admit(httptest.NewRecorder(), requestOf(6), 1<<20)
	if !ok {
		t.Fatal("budget not returned on release")
	}
	defer again()
	if _, ok := Admit(httptest.NewRecorder(), requestOf(6), 1<<20); ok {
		t.Fatal("double release freed budget twice")
	}
}

// A lone upload whose reservation exceeds the whole budget (a 50 MiB match log
// under a small dev budget) must still run when nothing else is in flight —
// otherwise it is refused forever.
func TestAdmitClampsALoneOversizedUploadToTheBudget(t *testing.T) {
	setBudget(t, 10)

	r := requestOf(0)
	r.ContentLength = -1 // unknown: reserves the route max
	big, ok := Admit(httptest.NewRecorder(), r, 50<<20)
	if !ok {
		t.Fatal("oversized upload refused with nothing in flight")
	}
	if _, ok := Admit(httptest.NewRecorder(), requestOf(1), 1<<20); ok {
		t.Fatal("a second upload got in beside one holding the whole budget")
	}
	big()
	small, ok := Admit(httptest.NewRecorder(), requestOf(1), 1<<20)
	if !ok {
		t.Fatal("budget not returned after the oversized upload")
	}
	small()
}

// Body must produce exactly what the old json.Marshal of the full map did —
// the workers parse this message, and the golden comparison is the proof that
// cutting the copies changed no byte.
func TestBodyIsByteIdenticalToMarshallingTheWholeMap(t *testing.T) {
	raw := []byte("PNG\x00\xff<&>" + strings.Repeat("payload", 1000))
	cases := map[string]map[string]any{
		"middle key": {"access_token": "t<k>&", "content_type": "image/png", "filename": "ä \"x\".png", "id": "7"},
		"key first":  {"identity": map[string]any{"user_id": 7, "roles": []any{"a"}}, "slug": "s"},
		"key last":   {"aaa": 1},
		"no fields":  {},
	}
	for name, fields := range cases {
		old := map[string]any{"content_b64": base64.StdEncoding.EncodeToString(raw)}
		for k, v := range fields {
			old[k] = v
		}
		want, _ := json.Marshal(old)

		got, err := Body(fields, "content_b64", Base64Len(int64(len(raw))), func(out []byte) ([]byte, error) {
			return AppendBase64(out, bytes.NewReader(raw))
		})
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if !bytes.Equal(got, want) {
			t.Errorf("%s:\n got %.200s\nwant %.200s", name, got, want)
		}
		if cap(got) > len(got)+2 {
			t.Errorf("%s: message regrew to cap %d for %d bytes (size hint wrong)", name, cap(got), len(got))
		}
	}
}
