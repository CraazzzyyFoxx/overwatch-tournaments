// dump-openapi prints the gateway's derived OpenAPI 3.1 document.
//
//	go run ./cmd/dump-openapi public > public.json
//	go run ./cmd/dump-openapi admin  > admin.json
package main

import (
	"fmt"
	"os"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apidocs"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/openapi"
)

func main() {
	kind := "public"
	if len(os.Args) > 1 {
		kind = os.Args[1]
	}
	publicGroups, adminGroups := apidocs.Groups()
	info := openapi.Info{
		Title:       "anak-tournaments gateway API",
		Version:     "dev",
		Description: "Derived from gateway route tables + Pydantic schemas.json.",
	}
	var body []byte
	switch kind {
	case "public":
		body = openapi.Build(info, publicGroups)
	case "admin":
		body = openapi.Build(info, adminGroups)
	default:
		fmt.Fprintf(os.Stderr, "usage: dump-openapi [public|admin]\n")
		os.Exit(2)
	}
	if _, err := os.Stdout.Write(body); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
