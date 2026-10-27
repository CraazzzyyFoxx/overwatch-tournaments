package workspace

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// set stores v unfenced. Lookups store through fill; tests seed with this.
func (c *ttlCache[K, V]) set(k K, v V) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.setLocked(k, v)
}

func (c *ttlCache[K, V]) capacity() int { return c.maxEntries }

// storeCache is what the Store-wide tests need from each of its caches.
type storeCache interface {
	generation() uint64
	capacity() int
}

// storeCaches lists every cache a Store holds; keep it in step with Store.
func storeCaches(s *Store) map[string]storeCache {
	return map[string]storeCache{
		"tournament":    s.tournament,
		"members":       s.members,
		"organizers":    s.organizers,
		"customDomains": s.customDomains,
		"hidden":        s.hidden,
		"preview":       s.preview,
		"encOwner":      s.encOwner,
		"mixMembers":    s.mixMembers,
		"captains":      s.captains,
		"draftCaptains": s.draftCaptains,
		"draftHosts":    s.draftHosts,
		"draftOwner":    s.draftOwner,
		"roomSettings":  s.roomSettings,
		"wsRPM":         s.wsRPM,
	}
}

func TestTTLCache(t *testing.T) {
	c := newBoundedTTLCache[int64, int64](time.Minute, 8)
	clock := time.Unix(1000, 0)
	c.now = func() time.Time { return clock }

	if _, ok := c.get(1); ok {
		t.Fatal("empty cache should miss")
	}

	c.set(1, 42)
	if v, ok := c.get(1); !ok || v != 42 {
		t.Fatalf("expected hit 42, got %d ok=%v", v, ok)
	}

	// Still fresh just before expiry.
	clock = clock.Add(59 * time.Second)
	if _, ok := c.get(1); !ok {
		t.Fatal("entry should still be fresh")
	}

	// Expired after TTL.
	clock = clock.Add(2 * time.Second)
	if _, ok := c.get(1); ok {
		t.Fatal("entry should have expired")
	}
}

// An expired entry used to leave the map only when its own key was read
// again, so under a stream of distinct keys the ttl never freed memory. The
// next insertion must reclaim every expired entry, and only those.
func TestTTLCache_InsertionReclaimsExpiredEntries(t *testing.T) {
	c := newBoundedTTLCache[int, bool](time.Minute, 100)
	clock := time.Unix(1000, 0)
	c.now = func() time.Time { return clock }

	for i := range 10 {
		c.set(i, true)
	}
	clock = clock.Add(30 * time.Second)
	c.set(10, true)
	clock = clock.Add(31 * time.Second) // 0..9 expired, 10 still fresh
	c.set(11, true)

	if len(c.m) != 2 || c.ll.Len() != 2 {
		t.Fatalf("after an insertion past the ttl: %d map / %d list entries, want 2", len(c.m), c.ll.Len())
	}
	if _, ok := c.get(10); !ok {
		t.Fatal("an unexpired entry must survive the reclaim")
	}
}

// Every Store cache is keyed by something a client picks in a subscribe (or
// an anonymous request), so none may grow without bound.
func TestStore_EveryCacheIsBounded(t *testing.T) {
	for name, c := range storeCaches(New(nil)) {
		if c.capacity() <= 0 {
			t.Errorf("the %s cache is unbounded", name)
		}
	}
}

// TestBoundedTTLCache_EvictsOldestOnOverflow proves the cardinality guard
// that closes the availability hole in ws.Handler's custom-domain Origin
// lookup: once a bounded cache is at capacity, inserting a new key evicts
// the least-recently-set entry (FIFO), never growing past maxEntries live
// keys — a flood of distinct attacker-chosen keys cannot inflate the map
// without bound.
func TestBoundedTTLCache_EvictsOldestOnOverflow(t *testing.T) {
	const maxEntries = 3
	c := newBoundedTTLCache[string, bool](time.Minute, maxEntries)

	c.set("a", true)
	c.set("b", true)
	c.set("c", true)
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after filling to capacity: len(m) = %d, want %d", got, maxEntries)
	}

	// "d" overflows the cache: "a" (oldest-set) must be evicted, and the
	// live-key count must never exceed maxEntries.
	c.set("d", true)
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after overflow: len(m) = %d, want %d (still bounded)", got, maxEntries)
	}
	if _, ok := c.get("a"); ok {
		t.Fatal(`"a" should have been evicted as the oldest entry`)
	}
	for _, k := range []string{"b", "c", "d"} {
		if _, ok := c.get(k); !ok {
			t.Fatalf("%q should still be cached", k)
		}
	}

	// Flooding with many more distinct keys must never grow the cache past
	// maxEntries — this is the direct regression test for the
	// distinct-Origin-host flood described in the CSWSH/DoS review.
	for i := 0; i < 1000; i++ {
		c.set(fmt.Sprintf("flood-%d", i), true)
	}
	if got := len(c.m); got != maxEntries {
		t.Fatalf("after a 1000-key flood: len(m) = %d, want %d (bound violated)", got, maxEntries)
	}
}

// TestBoundedTTLCache_RefreshProtectsFromEviction proves that a key which
// keeps getting legitimately refreshed (a real, actively-used custom domain)
// is moved to the back of the eviction order on each set, so it is NOT the
// eviction target while a colder entry is — a flood of new distinct keys
// evicts itself before it evicts something still in active use.
func TestBoundedTTLCache_RefreshProtectsFromEviction(t *testing.T) {
	const maxEntries = 3
	c := newBoundedTTLCache[string, bool](time.Minute, maxEntries)

	c.set("hot", true)
	c.set("b", true)
	c.set("c", true) // cache at capacity: order is hot, b, c (oldest -> newest)

	c.set("hot", true) // refresh: moves "hot" to the back -> order is b, c, hot

	c.set("d", true) // overflow: evicts "b" (now the oldest), not "hot"

	if _, ok := c.get("hot"); !ok {
		t.Fatal(`"hot" was refreshed and should have survived the overflow eviction`)
	}
	if _, ok := c.get("b"); ok {
		t.Fatal(`"b" should have been evicted (it was the oldest after "hot" was refreshed)`)
	}
}

// TestBoundedTTLCache_CachesNegativeResultsLikePositiveOnes proves the cache
// itself treats a cached "false" (e.g. host-not-verified) exactly like a
// cached "true": a single set is enough to make subsequent get calls hit,
// with no special-casing of the boolean value. This is the low-level
// building block behind Store.IsVerifiedCustomDomain's negative caching
// (verified=false is cached exactly like verified=true — see its doc
// comment) — a flood of lookups for the SAME unverified host costs at most
// one query per TTL, identically to a verified one.
func TestBoundedTTLCache_CachesNegativeResultsLikePositiveOnes(t *testing.T) {
	c := newBoundedTTLCache[string, bool](time.Minute, 8)

	c.set("verified.example.com", true)
	c.set("not-verified.example.com", false)

	v, ok := c.get("verified.example.com")
	if !ok || !v {
		t.Fatalf("verified.example.com: got (%v, %v), want (true, true)", v, ok)
	}

	v, ok = c.get("not-verified.example.com")
	if !ok || v {
		t.Fatalf("not-verified.example.com: got (%v, %v), want (false, true) — a cached negative result", v, ok)
	}
}

// identity-svc announces realtime:user:{id}:rbac after a membership or role
// change. Store.EvictUser must drop that user's answers at once (a removed
// member is refused, a new one admitted, on the very next subscribe) and keep
// a lookup that read the database before the change from caching it after.
// Other users' answers stay put.
func TestStore_EvictUserDropsThatUsersMembershipAnswers(t *testing.T) {
	s := New(nil)
	removed, other := memberKey{userID: 1, workspaceID: 10}, memberKey{userID: 2, workspaceID: 10}
	s.members.set(removed, true)
	s.members.set(other, true)
	s.organizers.set(removed, true)
	inFlight := s.members.generation() // a lookup for user 1 already querying

	s.EvictUser(1)

	if _, ok := s.members.get(removed); ok {
		t.Fatal("user 1's membership must be re-read after their RBAC change")
	}
	if _, ok := s.organizers.get(removed); ok {
		t.Fatal("user 1's organizer answer must be re-read after their RBAC change")
	}
	if v, ok := s.members.get(other); !ok || !v {
		t.Fatalf("user 2's membership must stay cached, got (%v, %v)", v, ok)
	}

	s.members.setIfCurrent(removed, true, inFlight)
	if _, ok := s.members.get(removed); ok {
		t.Fatal("an answer read before the eviction must not be cached after it")
	}
	s.members.setIfCurrent(removed, false, s.members.generation())
	if v, ok := s.members.get(removed); !ok || v {
		t.Fatalf("a lookup started after the eviction must cache, got (%v, %v)", v, ok)
	}
}

// A replaced draft captain is announced as chat.visibility_changed on the
// session's chat topic. The revoker's invalidation must drop that session's
// captain answers (and fence a lookup already querying), or the former captain
// is re-admitted from cache. Another session's answers stay put.
func TestStore_InvalidateRoomAccessDropsTheDraftsCaptainAnswers(t *testing.T) {
	s := New(nil)
	former, other := draftCaptainKey{userID: 1, sessionID: 7}, draftCaptainKey{userID: 1, sessionID: 8}
	s.draftCaptains.set(former, true)
	s.draftCaptains.set(other, true)
	s.roomSettings.set(roomKey{kind: "draft", refID: 7}, false)
	inFlight := s.draftCaptains.generation()

	s.InvalidateRoomAccess("draft", 7)

	if _, ok := s.draftCaptains.get(former); ok {
		t.Fatal("session 7's captain answers must be re-read after its captain changed")
	}
	if _, ok := s.roomSettings.get(roomKey{kind: "draft", refID: 7}); ok {
		t.Fatal("the room's spectator setting must be re-read too")
	}
	if v, ok := s.draftCaptains.get(other); !ok || !v {
		t.Fatalf("session 8's captain answer must stay cached, got (%v, %v)", v, ok)
	}
	s.draftCaptains.setIfCurrent(former, true, inFlight)
	if _, ok := s.draftCaptains.get(former); ok {
		t.Fatal("an answer read before the invalidation must not be cached after it")
	}
}

// An organizer closes a chat while a spectator-setting read is in flight. That
// read saw "spectators allowed"; storing it after the invalidation would hand
// the revoker's re-check the pre-toggle answer and keep the spectator in.
func TestStore_InvalidateRoomAccessFencesTheSettingsFill(t *testing.T) {
	s := New(nil)
	key := roomKey{kind: "encounter", refID: 3}
	inFlight := s.roomSettings.generation()

	s.InvalidateRoomAccess("encounter", 3)

	s.roomSettings.setIfCurrent(key, true, inFlight)
	if _, ok := s.roomSettings.get(key); ok {
		t.Fatal("a settings read that started before the invalidation must not be cached after it")
	}
}

// After the realtime bus lost frames (a Redis re-subscription) no cached
// answer is known to be current: Reset must empty every cache and keep a
// lookup already in flight from storing what it read before.
func TestStore_ResetFlushesAndFencesEveryCache(t *testing.T) {
	s := New(nil)
	key := memberKey{userID: 1, workspaceID: 10}
	s.members.set(key, true)
	s.customDomains.set("tenant.example.com", true)
	inFlight := s.members.generation()
	before := map[string]uint64{}
	for name, c := range storeCaches(s) {
		before[name] = c.generation()
	}

	s.Reset()

	for name, c := range storeCaches(s) {
		if c.generation() == before[name] {
			t.Errorf("Reset did not flush the %s cache", name)
		}
	}
	if _, ok := s.members.get(key); ok {
		t.Fatal("a membership cached before the reset must be re-read")
	}
	if _, ok := s.customDomains.get("tenant.example.com"); ok {
		t.Fatal("a custom-domain answer cached before the reset must be re-read")
	}
	s.members.setIfCurrent(key, true, inFlight)
	if _, ok := s.members.get(key); ok {
		t.Fatal("an answer read before the reset must not be cached after it")
	}
}

// A reconnect herd subscribing to one cold key used to fire one query per
// socket until the first answer landed. Concurrent misses for one key must
// share one query, and its answer must be cached for everyone after.
func TestFill_CollapsesConcurrentMisses(t *testing.T) {
	c := newBoundedTTLCache[string, bool](time.Minute, 8)
	var queries atomic.Int32
	release := make(chan struct{})
	fetch := func(context.Context) (bool, bool, error) {
		queries.Add(1)
		<-release
		return true, true, nil
	}

	const callers = 16
	var wg sync.WaitGroup
	for range callers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if v, found, err := c.fill(context.Background(), "cold.example.com", fetch); err != nil || !found || !v {
				t.Errorf("fill = (%v, %v, %v), want (true, true, nil)", v, found, err)
			}
		}()
	}
	// Hold the first query until the others have had time to join its flight.
	for queries.Load() == 0 {
		time.Sleep(time.Millisecond)
	}
	time.Sleep(50 * time.Millisecond)
	close(release)
	wg.Wait()

	if n := queries.Load(); n != 1 {
		t.Fatalf("%d concurrent misses ran %d queries, want 1", callers, n)
	}
	if v, ok := c.get("cold.example.com"); !ok || !v {
		t.Fatalf("the shared answer must be cached, got (%v, %v)", v, ok)
	}
}

// A lookup that starts after an eviction (an RBAC change, a closed chat) must
// neither join nor be answered by a query that started before it, and that
// older query must not overwrite the newer answer when it finally lands.
func TestFill_LookupAfterEvictionRunsItsOwnQuery(t *testing.T) {
	c := newBoundedTTLCache[memberKey, bool](time.Minute, 8)
	key := memberKey{userID: 1, workspaceID: 10}
	entered, release := make(chan struct{}), make(chan struct{})
	stale := make(chan bool)
	go func() {
		v, _, _ := c.fill(context.Background(), key, func(context.Context) (bool, bool, error) {
			close(entered)
			<-release
			return true, true, nil // read while the user was still a member
		})
		stale <- v
	}()
	<-entered

	c.evictWhere(func(k memberKey) bool { return k.userID == 1 })

	// Joining the pre-eviction flight would block until release; the timeout
	// turns that into a failure instead of a hang.
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	v, _, err := c.fill(ctx, key, func(context.Context) (bool, bool, error) { return false, true, nil })
	if err != nil || v {
		t.Fatalf("post-eviction fill = (%v, %v), want its own (false, nil)", v, err)
	}
	close(release)
	if !<-stale {
		t.Fatal("the pre-eviction caller must still get its own answer")
	}
	if v, ok := c.get(key); !ok || v {
		t.Fatalf("the pre-eviction answer must not replace the newer one, got (%v, %v)", v, ok)
	}
}

// The caller that started a flight hanging up (a socket closing mid-subscribe)
// must not fail the callers that joined it: a failed lookup is a denial, and
// on the revoker's path a revocation.
func TestFill_LeaderLeavingDoesNotFailTheFlight(t *testing.T) {
	c := newBoundedTTLCache[int64, bool](time.Minute, 8)
	entered, release := make(chan struct{}), make(chan struct{})
	fetch := func(ctx context.Context) (bool, bool, error) {
		close(entered)
		select {
		case <-release:
			return true, true, nil
		case <-ctx.Done():
			return false, false, ctx.Err()
		}
	}

	leaderCtx, leave := context.WithCancel(context.Background())
	leader := make(chan error)
	go func() {
		_, _, err := c.fill(leaderCtx, 7, fetch)
		leader <- err
	}()
	<-entered
	joined := make(chan error)
	go func() {
		v, _, err := c.fill(context.Background(), 7, fetch)
		if err == nil && !v {
			err = errors.New("got false")
		}
		joined <- err
	}()
	time.Sleep(50 * time.Millisecond) // let the second caller join the flight

	leave()
	if err := <-leader; !errors.Is(err, context.Canceled) {
		t.Fatalf("the departed caller must get its own cancellation, got %v", err)
	}
	close(release)
	if err := <-joined; err != nil {
		t.Fatalf("the joined caller must still get the answer, got %v", err)
	}
}
