// Runs only mocked browser APIs; never opens or inspects a real browser profile.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const code = fs.readFileSync(path.join(__dirname, "../assets/identity/identity.js"), "utf8");
const candidate = "N".repeat(43);
const previous = "P".repeat(43);

function boot(saved = null, blocked = false) {
  const messages = [];
  const listeners = {};
  const storage = new Map(saved ? [["animeway.private-profile.v1", saved]] : []);
  const parent = { postMessage: (message, origin) => messages.push({ message, origin }) };
  const window = {
    parent, location: { origin: "http://localhost:8501" },
    localStorage: {
      getItem(key) { if (blocked) throw Error("blocked"); return storage.get(key) ?? null; },
      setItem(key, value) { if (blocked) throw Error("blocked"); storage.set(key, value); },
    },
    addEventListener: (name, handler) => { listeners[name] = handler; },
  };
  vm.runInNewContext(code, { window });
  const render = (args, overrides = {}) => listeners.message({
    source: parent, origin: window.location.origin,
    data: { type: "streamlit:render", args }, ...overrides,
  });
  const values = () => messages.filter(({ message }) => message.type === "streamlit:setComponentValue").map(({ message }) => message.value);
  return { render, values, messages, storage };
}

let instance = boot();
instance.render({ candidate });
assert.equal(instance.values()[0].token, candidate);
assert.equal(instance.values()[0].persistent, true);
assert.equal(instance.storage.get("animeway.private-profile.v1"), candidate);
instance.render({ candidate });
assert.equal(instance.values().length, 1, "same identity must not cause a rerun loop");
assert.ok(instance.messages.every(({ origin }) => origin === "http://localhost:8501"));

instance = boot(previous);
instance.render({ candidate });
assert.equal(instance.values()[0].token, previous, "a new app session must reuse the browser identity");
instance.render({ candidate, replace_invalid_token: previous });
assert.equal(instance.values()[1].token, candidate);

instance = boot(null, true);
instance.render({ candidate });
assert.equal(instance.values()[0].persistent, false);

instance = boot();
instance.render({ candidate }, { origin: "https://untrusted.example" });
instance.render({ candidate }, { source: {} });
instance.render({ candidate: "malformed" });
assert.equal(instance.values().length, 0, "foreign origins/frames and invalid credentials are ignored");
console.log("Identity protocol, recovery, origin validation and storage failure: OK");
