package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	root := getenv("NETWORKCLAW_WEB2_DIST", "/opt/networkclaw-web2/dist")
	backend, err := url.Parse(getenv("NETWORKCLAW_WEB2_LOBBY_URL", "http://lobby:8080"))
	if err != nil || (backend.Scheme != "http" && backend.Scheme != "https") || backend.Host == "" {
		log.Fatal("invalid NETWORKCLAW_WEB2_LOBBY_URL")
	}
	addr := getenv("NETWORKCLAW_WEB2_ADDR", ":5174")
	log.Printf("web2 listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, handler(root, backend)))
}

func handler(root string, backend *url.URL) http.Handler {
	proxy := httputil.NewSingleHostReverseProxy(backend)
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("lobby proxy error: %v", err)
		http.Error(w, "backend unavailable", http.StatusBadGateway)
	}
	files := http.FileServer(http.Dir(root))
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if _, err := os.Stat(filepath.Join(root, "index.html")); err != nil {
			http.Error(w, "frontend unavailable", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/api/", proxy.ServeHTTP)
	mux.HandleFunc("/ws", proxy.ServeHTTP)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		path := filepath.Join(root, filepath.FromSlash(strings.TrimPrefix(r.URL.Path, "/")))
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			files.ServeHTTP(w, r)
			return
		}
		http.ServeFile(w, r, filepath.Join(root, "index.html"))
	})
	return mux
}

func getenv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
