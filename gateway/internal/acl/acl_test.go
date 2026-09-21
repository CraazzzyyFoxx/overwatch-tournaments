package acl

import (
	"context"
	"errors"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
)

type fakeResolver struct {
	workspaceID int64
	found       bool
	err         error
}

func (f fakeResolver) TournamentWorkspaceID(context.Context, int64) (int64, bool, error) {
	return f.workspaceID, f.found, f.err
}

type fakeMembers struct {
	member       bool
	captain      bool
	draftCaptain bool
	err          error
	calls        []memberCall
}

type memberCall struct{ user, ws int64 }

func (f *fakeMembers) IsWorkspaceMember(_ context.Context, userID, workspaceID int64) (bool, error) {
	f.calls = append(f.calls, memberCall{userID, workspaceID})
	return f.member, f.err
}

func (f *fakeMembers) IsEncounterCaptain(context.Context, int64, int64) (bool, error) {
	return f.captain, f.err
}

func (f *fakeMembers) IsDraftSessionCaptain(context.Context, int64, int64) (bool, error) {
	return f.draftCaptain, f.err
}

// fakeVis defaults to a visible (found, not hidden) tournament so spectating
// topics stay public unless a test opts into hidden.
type fakeVis struct {
	hidden        bool
	hiddenFound   bool
	preview       bool
	encTID        int64
	encFound      bool
	draftTID      int64
	draftFound    bool
	spectatorRead bool
	err           error
}

func (f fakeVis) TournamentIsHidden(context.Context, int64) (bool, bool, error) {
	return f.hidden, f.hiddenFound, f.err
}

func (f fakeVis) IsPreviewAllowed(context.Context, int64, int64) (bool, error) {
	return f.preview, f.err
}

func (f fakeVis) EncounterTournamentID(context.Context, int64) (int64, bool, error) {
	return f.encTID, f.encFound, f.err
}

func (f fakeVis) DraftSessionTournamentID(context.Context, int64) (int64, bool, error) {
	return f.draftTID, f.draftFound, f.err
}

func (f fakeVis) RoomSpectatorRead(context.Context, string, int64) (bool, error) {
	return f.spectatorRead, f.err
}

// visibleVis: a real, non-hidden tournament (public spectating stays open).
func visibleVis() fakeVis { return fakeVis{hiddenFound: true, hidden: false} }

func TestPatternMatch(t *testing.T) {
	p := NewPattern("tournament:*:balancer")
	if g, ok := p.Match("tournament:42:balancer"); !ok || len(g) != 1 || g[0] != "42" {
		t.Fatalf("expected match with [42], got %v ok=%v", g, ok)
	}
	if _, ok := p.Match("tournament:42:bracket"); ok {
		t.Fatal("should not match different suffix")
	}
	if _, ok := p.Match("tournament:42"); ok {
		t.Fatal("should not match different segment count")
	}
}

func TestAllow_SpectatePublicWhenNotHidden(t *testing.T) {
	r := New(fakeResolver{}, &fakeMembers{}, visibleVis())
	for _, topic := range []string{"tournament:1:bracket", "tournament:1:draft"} {
		ok, err := r.Allow(context.Background(), nil, topic) // anonymous
		if err != nil || !ok {
			t.Fatalf("%s should be allowed for anon on a visible tournament: ok=%v err=%v", topic, ok, err)
		}
	}
}

func TestAllow_SpectateUnknownTournamentDenied(t *testing.T) {
	// found=false -> deny (no existence disclosure).
	r := New(fakeResolver{}, &fakeMembers{}, fakeVis{hiddenFound: false})
	if ok, _ := r.Allow(context.Background(), nil, "tournament:1:bracket"); ok {
		t.Fatal("unknown tournament must be denied")
	}
}

func TestAllow_SpectateHiddenTournament(t *testing.T) {
	ctx := context.Background()
	hiddenVis := fakeVis{hiddenFound: true, hidden: true}

	t.Run("anonymous denied", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{}, hiddenVis)
		if ok, _ := r.Allow(ctx, nil, "tournament:42:bracket"); ok {
			t.Fatal("anon must be denied a hidden tournament")
		}
	})

	t.Run("superuser allowed", func(t *testing.T) {
		r := New(fakeResolver{found: false}, &fakeMembers{}, hiddenVis)
		su := &auth.User{ID: 9, IsSuperuser: true}
		if ok, err := r.Allow(ctx, su, "tournament:42:draft"); err != nil || !ok {
			t.Fatalf("superuser should be allowed: ok=%v err=%v", ok, err)
		}
	})

	t.Run("workspace member allowed", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: true}, hiddenVis)
		if ok, err := r.Allow(ctx, &auth.User{ID: 7}, "tournament:42:bracket"); err != nil || !ok {
			t.Fatalf("member should be allowed: ok=%v err=%v", ok, err)
		}
	})

	t.Run("preview-allowlisted allowed", func(t *testing.T) {
		vis := fakeVis{hiddenFound: true, hidden: true, preview: true}
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false}, vis)
		if ok, err := r.Allow(ctx, &auth.User{ID: 7}, "tournament:42:bracket"); err != nil || !ok {
			t.Fatalf("allowlisted user should be allowed: ok=%v err=%v", ok, err)
		}
	})

	t.Run("outsider denied", func(t *testing.T) {
		vis := fakeVis{hiddenFound: true, hidden: true, preview: false}
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false}, vis)
		if ok, _ := r.Allow(ctx, &auth.User{ID: 7}, "tournament:42:bracket"); ok {
			t.Fatal("non-member, non-allowlisted user must be denied")
		}
	})
}

func TestAllow_SpectateHiddenEncounterMapVeto(t *testing.T) {
	ctx := context.Background()
	// encounter 5 -> tournament 42, hidden.
	vis := fakeVis{hiddenFound: true, hidden: true, encTID: 42, encFound: true}
	r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false}, vis)
	if ok, _ := r.Allow(ctx, nil, "encounter:5:map-veto"); ok {
		t.Fatal("anon must be denied a hidden tournament's map-veto")
	}
	su := &auth.User{ID: 9, IsSuperuser: true}
	if ok, err := r.Allow(ctx, su, "encounter:5:map-veto"); err != nil || !ok {
		t.Fatalf("superuser should be allowed hidden map-veto: ok=%v err=%v", ok, err)
	}
}

func TestAllow_SpectateHiddenEncounterPickBanHero(t *testing.T) {
	ctx := context.Background()
	// encounter 5 -> tournament 42, hidden.
	vis := fakeVis{hiddenFound: true, hidden: true, encTID: 42, encFound: true}
	r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false}, vis)
	if ok, _ := r.Allow(ctx, nil, "encounter:5:pick-ban:hero"); ok {
		t.Fatal("anon must be denied a hidden tournament's hero pick-ban topic")
	}
	su := &auth.User{ID: 9, IsSuperuser: true}
	if ok, err := r.Allow(ctx, su, "encounter:5:pick-ban:hero"); err != nil || !ok {
		t.Fatalf("superuser should be allowed hidden hero pick-ban topic: ok=%v err=%v", ok, err)
	}
}

// Both chat rooms behave the same way: participants (captain / workspace
// member / superuser) always get in, and everyone else — anonymous included —
// only while the organizer leaves spectator read ON. The toggle widens the
// audience of a room the caller could already see; it never unhides a hidden
// tournament.
func TestAllow_RoomChat(t *testing.T) {
	ctx := context.Background()
	user := &auth.User{ID: 7}
	su := &auth.User{ID: 9, IsSuperuser: true}

	rooms := []struct {
		name    string
		topic   string
		captain func() *fakeMembers
	}{
		{"encounter", "encounter:1:chat", func() *fakeMembers { return &fakeMembers{captain: true} }},
		{"draft", "draft:1:chat", func() *fakeMembers { return &fakeMembers{draftCaptain: true} }},
	}

	for _, room := range rooms {
		t.Run(room.name, func(t *testing.T) {
			cases := []struct {
				name    string
				user    *auth.User
				members *fakeMembers
				open    bool
				hidden  bool
				want    bool
			}{
				{"anonymous denied when closed", nil, &fakeMembers{}, false, false, false},
				{"anonymous allowed when open", nil, &fakeMembers{}, true, false, true},
				{"non-participant denied when closed", user, &fakeMembers{}, false, false, false},
				{"non-participant allowed when open", user, &fakeMembers{}, true, false, true},
				{"captain allowed when closed", user, room.captain(), false, false, true},
				{"captain allowed when open", user, room.captain(), true, false, true},
				{"workspace member allowed when closed", user, &fakeMembers{member: true}, false, false, true},
				{"workspace member allowed when open", user, &fakeMembers{member: true}, true, false, true},
				{"superuser allowed when closed", su, &fakeMembers{}, false, false, true},
				{"hidden tournament outsider denied when open", user, &fakeMembers{}, true, true, false},
				{"hidden tournament anonymous denied when open", nil, &fakeMembers{}, true, true, false},
			}
			for _, tc := range cases {
				t.Run(tc.name, func(t *testing.T) {
					r := New(
						fakeResolver{workspaceID: 3, found: true},
						tc.members,
						fakeVis{
							hiddenFound:   true,
							hidden:        tc.hidden,
							encTID:        42,
							encFound:      true,
							draftTID:      42,
							draftFound:    true,
							spectatorRead: tc.open,
						},
					)
					ok, err := r.Allow(ctx, tc.user, room.topic)
					if err != nil {
						t.Fatalf("unexpected error: %v", err)
					}
					if ok != tc.want {
						t.Fatalf("Allow(%s) = %v, want %v", room.topic, ok, tc.want)
					}
				})
			}
		})
	}
}

// A room whose referent does not exist is denied even wide open — there is no
// tournament to apply the visibility gate to, and answering "allowed" would
// disclose which encounter/session ids exist.
func TestAllow_RoomChatUnknownReferentDenied(t *testing.T) {
	ctx := context.Background()
	vis := fakeVis{hiddenFound: true, spectatorRead: true, encFound: false, draftFound: false}
	r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{}, vis)
	for _, topic := range []string{"encounter:1:chat", "draft:1:chat"} {
		if ok, err := r.Allow(ctx, &auth.User{ID: 7}, topic); err != nil || ok {
			t.Fatalf("Allow(%s) = %v (err=%v), want denied", topic, ok, err)
		}
	}
}

func TestAllow_BalancerRequiresMembership(t *testing.T) {
	ctx := context.Background()
	user := &auth.User{ID: 7}

	t.Run("anonymous denied", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: true}, fakeVis{})
		if ok, _ := r.Allow(ctx, nil, "tournament:42:balancer"); ok {
			t.Fatal("anon must be denied")
		}
	})

	t.Run("member allowed", func(t *testing.T) {
		members := &fakeMembers{member: true}
		r := New(fakeResolver{workspaceID: 3, found: true}, members, fakeVis{})
		ok, err := r.Allow(ctx, user, "tournament:42:balancer")
		if err != nil || !ok {
			t.Fatalf("member should be allowed: ok=%v err=%v", ok, err)
		}
		if len(members.calls) != 1 || members.calls[0] != (memberCall{7, 3}) {
			t.Fatalf("expected membership check for (7,3), got %v", members.calls)
		}
	})

	t.Run("non-member denied", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false}, fakeVis{})
		if ok, _ := r.Allow(ctx, user, "tournament:42:balancer"); ok {
			t.Fatal("non-member must be denied")
		}
	})

	t.Run("unknown tournament denied", func(t *testing.T) {
		r := New(fakeResolver{found: false}, &fakeMembers{member: true}, fakeVis{})
		if ok, _ := r.Allow(ctx, user, "tournament:999:balancer"); ok {
			t.Fatal("unknown tournament must be denied")
		}
	})

	t.Run("resolver error propagates", func(t *testing.T) {
		r := New(fakeResolver{err: errors.New("db down")}, &fakeMembers{}, fakeVis{})
		if _, err := r.Allow(ctx, user, "tournament:42:balancer"); err == nil {
			t.Fatal("expected error to propagate")
		}
	})

	t.Run("superuser bypass without membership row", func(t *testing.T) {
		members := &fakeMembers{member: false}
		r := New(fakeResolver{found: false}, members, fakeVis{})
		su := &auth.User{ID: 9, IsSuperuser: true}
		ok, err := r.Allow(ctx, su, "tournament:42:balancer")
		if err != nil || !ok {
			t.Fatalf("superuser should be allowed: ok=%v err=%v", ok, err)
		}
		if len(members.calls) != 0 {
			t.Fatalf("superuser must bypass the membership check, got calls %v", members.calls)
		}
	})
}

func TestAllow_WorkspaceMember(t *testing.T) {
	ctx := context.Background()
	user := &auth.User{ID: 7}

	members := &fakeMembers{member: true}
	r := New(fakeResolver{}, members, fakeVis{})
	ok, err := r.Allow(ctx, user, "workspace:5:notifications")
	if err != nil || !ok {
		t.Fatalf("member should be allowed: ok=%v err=%v", ok, err)
	}
	if members.calls[0] != (memberCall{7, 5}) {
		t.Fatalf("expected membership check for (7,5), got %v", members.calls)
	}

	if ok, _ := r.Allow(ctx, nil, "workspace:5:notifications"); ok {
		t.Fatal("anon must be denied workspace topic")
	}

	suMembers := &fakeMembers{member: false}
	suR := New(fakeResolver{}, suMembers, fakeVis{})
	su := &auth.User{ID: 9, IsSuperuser: true}
	if ok, err := suR.Allow(ctx, su, "workspace:5:notifications"); err != nil || !ok {
		t.Fatalf("superuser should be allowed workspace topic: ok=%v err=%v", ok, err)
	}
	if len(suMembers.calls) != 0 {
		t.Fatalf("superuser must bypass the workspace membership check, got %v", suMembers.calls)
	}
}

// user:<id>:notifications is the personal inbox signal. It is the one topic
// with NO superuser bypass: nobody needs to read someone else's inbox, and a
// rule with no exception cannot be widened by accident later.
func TestAllow_OwnUserNotifications(t *testing.T) {
	ctx := context.Background()
	r := New(fakeResolver{}, &fakeMembers{member: true}, fakeVis{})

	cases := []struct {
		name  string
		user  *auth.User
		topic string
		want  bool
	}{
		{"owner", &auth.User{ID: 7}, "user:7:notifications", true},
		{"other user", &auth.User{ID: 8}, "user:7:notifications", false},
		{"anonymous", nil, "user:7:notifications", false},
		{"superuser has no bypass", &auth.User{ID: 8, IsSuperuser: true}, "user:7:notifications", false},
		{"unparseable id", &auth.User{ID: 7}, "user:abc:notifications", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ok, err := r.Allow(ctx, tc.user, tc.topic)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if ok != tc.want {
				t.Fatalf("Allow(%q) = %v, want %v", tc.topic, ok, tc.want)
			}
		})
	}
}

func TestAllow_UnknownTopicDenied(t *testing.T) {
	r := New(fakeResolver{}, &fakeMembers{member: true}, fakeVis{})
	if ok, _ := r.Allow(context.Background(), &auth.User{ID: 1}, "random:topic:here"); ok {
		t.Fatal("unknown topic must be denied")
	}
}
