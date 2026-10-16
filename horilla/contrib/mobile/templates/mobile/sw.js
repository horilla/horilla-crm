{% autoescape off %}/*
 * Horilla mobile service worker.
 *
 * Served from /m/sw.js, so its scope is /m/ and desktop pages are never
 * controlled by it. It answers only GET requests for static files carrying the
 * current asset version (?v=...) from its cache. Every other request, including
 * all HTML and HTMX responses and anything sent with an Authorization header,
 * goes to the network untouched.
 */
const ASSET_VERSION = {{ asset_version }};
const CACHE_PREFIX = {{ cache_prefix }};
const CACHE_NAME = {{ cache_name }};
const STATIC_BASE = new URL({{ static_url }}, self.location.origin).href;
const CACHE_ENABLED = {{ cache_enabled }};

function isVersionedStatic(request) {
    if (request.method !== "GET" || request.headers.has("Authorization")) {
        return false;
    }
    const url = new URL(request.url);
    return (
        url.href.startsWith(STATIC_BASE) &&
        url.searchParams.get("v") === ASSET_VERSION
    );
}

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
                        .map((key) => caches.delete(key))
                )
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    if (!CACHE_ENABLED || !isVersionedStatic(event.request)) {
        return;
    }
    event.respondWith(
        caches.open(CACHE_NAME).then((cache) =>
            cache.match(event.request).then(
                (cached) =>
                    cached ||
                    fetch(event.request).then((response) => {
                        if (response.ok) {
                            cache.put(event.request, response.clone());
                        }
                        return response;
                    })
            )
        )
    );
});
{% endautoescape %}
