package respcache

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// manifestPath resolves backend/shared/realtime/resources.json from this
// package. The gateway is a separate Go module in the same repository, so the
// manifest is read by path rather than imported — the point is that the two
// trees cannot drift, not that they share a package.
func manifestPath(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..", "..", "backend", "shared", "realtime", "resources.json")
}

// The parity gate. A resource published by the backend but missing here would
// silently fall into patternsFor's nil branch — correct (drop everything) but
// far more expensive than intended, and invisible. A rule left here after its
// resource is gone is dead code nobody would notice either.
func TestResourcePatternsMirrorManifest(t *testing.T) {
	raw, err := os.ReadFile(manifestPath(t))
	if err != nil {
		t.Fatalf("read manifest: %v", err)
	}
	var manifest struct {
		Version   int                       `json:"version"`
		Resources map[string]map[string]any `json:"resources"`
	}
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatalf("parse manifest: %v", err)
	}
	if manifest.Version != 1 {
		t.Fatalf("manifest version %d: payload shape changed, revisit eventResources()", manifest.Version)
	}

	var missing, extra []string
	for resource := range manifest.Resources {
		if _, ok := resourcePatterns[resource]; !ok {
			missing = append(missing, resource)
		}
	}
	for resource := range resourcePatterns {
		if _, ok := manifest.Resources[resource]; !ok {
			extra = append(extra, resource)
		}
	}
	sort.Strings(missing)
	sort.Strings(extra)
	if len(missing) > 0 {
		t.Errorf("resources in the manifest with no cache rule: %v (add an entry — empty slice if this cache holds nothing for it)", missing)
	}
	if len(extra) > 0 {
		t.Errorf("cache rules for resources absent from the manifest: %v", extra)
	}
}
