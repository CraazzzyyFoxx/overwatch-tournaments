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
	member bool
	err    error
	calls  []memberCall
}

type memberCall struct{ user, ws int64 }

func (f *fakeMembers) IsWorkspaceMember(_ context.Context, userID, workspaceID int64) (bool, error) {
	f.calls = append(f.calls, memberCall{userID, workspaceID})
	return f.member, f.err
}

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

func TestAllow_PublicTopics(t *testing.T) {
	r := New(fakeResolver{}, &fakeMembers{})
	for _, topic := range []string{"tournament:1:bracket", "tournament:1:draft"} {
		ok, err := r.Allow(context.Background(), nil, topic) // anonymous
		if err != nil || !ok {
			t.Fatalf("%s should be allowed for anon: ok=%v err=%v", topic, ok, err)
		}
	}
}

func TestAllow_BalancerRequiresMembership(t *testing.T) {
	ctx := context.Background()
	user := &auth.User{ID: 7}

	t.Run("anonymous denied", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: true})
		if ok, _ := r.Allow(ctx, nil, "tournament:42:balancer"); ok {
			t.Fatal("anon must be denied")
		}
	})

	t.Run("member allowed", func(t *testing.T) {
		members := &fakeMembers{member: true}
		r := New(fakeResolver{workspaceID: 3, found: true}, members)
		ok, err := r.Allow(ctx, user, "tournament:42:balancer")
		if err != nil || !ok {
			t.Fatalf("member should be allowed: ok=%v err=%v", ok, err)
		}
		if len(members.calls) != 1 || members.calls[0] != (memberCall{7, 3}) {
			t.Fatalf("expected membership check for (7,3), got %v", members.calls)
		}
	})

	t.Run("non-member denied", func(t *testing.T) {
		r := New(fakeResolver{workspaceID: 3, found: true}, &fakeMembers{member: false})
		if ok, _ := r.Allow(ctx, user, "tournament:42:balancer"); ok {
			t.Fatal("non-member must be denied")
		}
	})

	t.Run("unknown tournament denied", func(t *testing.T) {
		r := New(fakeResolver{found: false}, &fakeMembers{member: true})
		if ok, _ := r.Allow(ctx, user, "tournament:999:balancer"); ok {
			t.Fatal("unknown tournament must be denied")
		}
	})

	t.Run("resolver error propagates", func(t *testing.T) {
		r := New(fakeResolver{err: errors.New("db down")}, &fakeMembers{})
		if _, err := r.Allow(ctx, user, "tournament:42:balancer"); err == nil {
			t.Fatal("expected error to propagate")
		}
	})
}

func TestAllow_WorkspaceMember(t *testing.T) {
	ctx := context.Background()
	user := &auth.User{ID: 7}

	members := &fakeMembers{member: true}
	r := New(fakeResolver{}, members)
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
}

func TestAllow_UnknownTopicDenied(t *testing.T) {
	r := New(fakeResolver{}, &fakeMembers{member: true})
	if ok, _ := r.Allow(context.Background(), &auth.User{ID: 1}, "random:topic:here"); ok {
		t.Fatal("unknown topic must be denied")
	}
}
