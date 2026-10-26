// Package authtest mints access tokens the way identity-svc does (EdDSA, the
// claims of its TokenCodec) for the tests of every package that verifies them.
package authtest

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// PublicKey verifies every token Sign mints; hand it to auth.New.
var PublicKey, privateKey, _ = ed25519.GenerateKey(nil)

// Claims are a valid access token's claims for user sub, an hour from expiry.
// The jti is random, so two tokens minted for one user are distinct.
func Claims(sub string) jwt.MapClaims {
	jti := make([]byte, 16)
	_, _ = rand.Read(jti)
	now := time.Now()
	return jwt.MapClaims{
		"sub":  sub,
		"sid":  "00000000-0000-4000-8000-000000000001",
		"type": "access",
		"iat":  now.Unix(),
		"exp":  now.Add(time.Hour).Unix(),
		"iss":  "owt-identity",
		"aud":  "owt",
		"jti":  hex.EncodeToString(jti),
	}
}

// Token is a valid access token for user sub.
func Token(sub string) string {
	return Sign(Claims(sub))
}

// Sign signs claims with the test key. Ed25519 signing with a well-formed key
// cannot fail, so it panics rather than taking a *testing.T.
func Sign(claims jwt.MapClaims) string {
	s, err := jwt.NewWithClaims(jwt.SigningMethodEdDSA, claims).SignedString(privateKey)
	if err != nil {
		panic(err)
	}
	return s
}
