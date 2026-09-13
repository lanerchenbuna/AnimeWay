/* First-party, dependency-free Streamlit component. No credentials in URLs. */
(() => {
  "use strict";
  const STORAGE_KEY = "animeway.private-profile.v1";
  const validToken = (value) => typeof value === "string" && /^[A-Za-z0-9_-]{40,128}$/.test(value);
  let lastValue = "";
  let currentArgs = null;
  const parentOrigin = window.location.origin;
  const send = (type, extra = {}) => window.parent.postMessage(
    { isStreamlitMessage: true, type, ...extra }, parentOrigin
  );

  function resolveIdentity(args) {
    if (!validToken(args.candidate)) return;
    let token = args.candidate;
    let persistent = true;
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (validToken(saved) && saved !== args.replace_invalid_token) token = saved;
      window.localStorage.setItem(STORAGE_KEY, token);
      persistent = window.localStorage.getItem(STORAGE_KEY) === token;
    } catch (_) {
      // Browsing still works in privacy modes. The UI explains backup/recovery.
      persistent = false;
    }
    const value = { token, persistent };
    const signature = JSON.stringify(value);
    if (signature !== lastValue) {
      lastValue = signature;
      send("streamlit:setComponentValue", { value, dataType: "json" });
    }
    send("streamlit:setFrameHeight", { height: 0 });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || event.origin !== parentOrigin) return;
    if (event.data?.type !== "streamlit:render") return;
    currentArgs = event.data.args || {};
    resolveIdentity(currentArgs);
  });
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY && currentArgs) resolveIdentity(currentArgs);
  });
  send("streamlit:componentReady", { apiVersion: 1 });
  send("streamlit:setFrameHeight", { height: 0 });
})();
