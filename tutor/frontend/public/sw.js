/**
 * Service worker.
 *
 * Two caches with different rules, because the two kinds of thing being cached
 * have opposite requirements.
 *
 * The **app shell** is cache-first: the JS and CSS are content-hashed by Vite, so
 * a cached copy is always correct and going to the network for it only adds
 * latency. Navigations fall back to the cached index when offline, which is what
 * makes the installed app open at all without a connection.
 *
 * **Lesson content** is network-first with a cache fallback. Fresh is better when
 * fresh is available -- a lesson can be regenerated, mastery moves -- but a lesson
 * already read must remain readable on a train. Only `GET /lessons/{id}` is
 * cached: it is the plain-JSON copy of prose that was streamed over SSE, and
 * caching it is the entire reason that endpoint exists.
 *
 * Nothing else from the API is cached. A stale concept graph or a stale due queue
 * is worse than an error, because the learner would act on it.
 */

const VERSION = "v1";
const SHELL_CACHE = `tutor-shell-${VERSION}`;
const LESSON_CACHE = `tutor-lessons-${VERSION}`;

const SHELL_ASSETS = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== LESSON_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

/** Whether a request is a lesson fetch worth keeping for offline reading. */
function isLessonRead(url) {
  return /\/lessons\/[^/]+$/.test(url.pathname);
}

/** Whether a request is for a build artefact that can be served from cache. */
function isShellAsset(url) {
  return (
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/assets/") ||
      SHELL_ASSETS.includes(url.pathname) ||
      url.pathname.endsWith(".svg") ||
      url.pathname.endsWith(".css"))
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/index.html").then((hit) => hit ?? Response.error()),
      ),
    );
    return;
  }

  if (isLessonRead(url)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(LESSON_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(request).then(
            (hit) =>
              hit ??
              new Response(JSON.stringify({ detail: "offline and not cached" }), {
                status: 503,
                headers: { "content-type": "application/json" },
              }),
          ),
        ),
    );
    return;
  }

  if (isShellAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
