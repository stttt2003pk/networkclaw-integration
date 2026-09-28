package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWeb2Routes(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "index.html"), []byte("WEB2_INDEX"), 0600); err != nil {
		t.Fatal(err)
	}
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "LOBBY:"+r.URL.Path)
	}))
	defer backend.Close()
	target, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	front := httptest.NewServer(handler(root, target))
	defer front.Close()
	for path, expected := range map[string]string{
		"/": "WEB2_INDEX", "/sessions/example": "WEB2_INDEX",
		"/api/v1/healthz": "LOBBY:/api/v1/healthz", "/ws": "LOBBY:/ws",
	} {
		response, err := http.Get(front.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 || !strings.Contains(string(body), expected) {
			t.Fatalf("%s: status=%d body=%q error=%v", path, response.StatusCode, body, err)
		}
	}
}
