package auth

import "context"

type userKey struct{}

// WithUser records the request's locally parsed principal — nil for anonymous
// — so middleware further in (metrics, the anonymous rate limiter) reuse it
// instead of verifying the same JWT again. It is the outermost observability
// middleware (httplog) that parses and stores it, before calling next.
func WithUser(ctx context.Context, u *User) context.Context {
	return context.WithValue(ctx, userKey{}, u)
}

// UserFromContext returns the principal WithUser stored. resolved is true even
// for an anonymous (nil) user; false means nothing parsed this request yet and
// the caller should fall back to Authenticator.UserFromRequest.
func UserFromContext(ctx context.Context) (u *User, resolved bool) {
	// A stored (*User)(nil) is a non-nil interface, so the assertion succeeds.
	u, resolved = ctx.Value(userKey{}).(*User)
	return u, resolved
}
