// Content scripts can't call localhost from https pages (CORS / mixed content); relay through here.
chrome.runtime.onMessage.addListener(({ path, body }, _, reply) => {
  fetch(`http://127.0.0.1:8766${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})
    .then(r => r.json()).then(reply, e => reply({ error: String(e), offline: e instanceof TypeError }));   // TypeError = can't connect
  return true;
});
// Toolbar icon opens the local player page.
chrome.action.onClicked.addListener(() => chrome.tabs.create({ url: chrome.runtime.getURL("player.html") }));
