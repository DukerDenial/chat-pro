self.addEventListener("install", event => {
  event.waitUntil(
    caches.open("chat-cache").then(cache => {
      return cache.addAll(["/", "/static/manifest.json"]);
    })
  );
});
