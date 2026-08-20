import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const serverUrl = new URL("../dist/server/index.js", import.meta.url);
  serverUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handleRequest } = await import(serverUrl.href);
  return handleRequest(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {},
  );
}

test("renders the SpeakBridge local application", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /SpeakBridge/);
  assert.match(html, /Hai chiều/);
  assert.match(html, /PHIÊN DỊCH HỌP HAI CHIỀU/);
  assert.match(html, /Bên kia nói/);
  assert.match(html, /Tôi nói/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview|Your site is taking shape/);
});
