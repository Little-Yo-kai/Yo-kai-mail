import assert from "node:assert/strict";
import { test } from "node:test";
import { readGenerationResponse } from "../lib/generation.ts";

function streamResponse(text, chunkSize = 7) {
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream({
    start(controller) {
      for (let start = 0; start < bytes.length; start += chunkSize) {
        controller.enqueue(bytes.slice(start, start + chunkSize));
      }
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": "application/x-ndjson" } });
}

test("reads real progress and a complete email across arbitrary UTF-8 chunks", async () => {
  const events = [];
  const result = await readGenerationResponse(streamResponse([
    { type: "started", timeout_seconds: 240 },
    { type: "progress", stage: "reference_selection" },
    { type: "heartbeat", stage: "email_design" },
    { type: "result", success: true, data: { subject: "Café ✉", html: "<html>Email</html>" } },
  ].map(JSON.stringify).join("\n"), 1), (event) => events.push(event));
  assert.equal(result.data.subject, "Café ✉");
  assert.equal(events[1].stage, "reference_selection");
  assert.equal(events.length, 4);
});

test("returns a provider failure with its actual stage", async () => {
  const result = await readGenerationResponse(streamResponse(JSON.stringify({
    type: "error", success: false, stage: "brand_analysis", error: "The AI provider is busy.",
  })), () => {});
  assert.equal(result.success, false);
  assert.equal(result.stage, "brand_analysis");
});

test("reports interrupted streams instead of leaving the page waiting", async () => {
  await assert.rejects(readGenerationResponse(streamResponse(
    '{"type":"progress","stage":"email_design"}\n',
  ), () => {}), /connection ended before the email was ready/i);
});

test("explains HTML gateway errors and upload validation failures", async () => {
  await assert.rejects(readGenerationResponse(new Response("<html>Gateway timeout</html>", {
    status: 504, headers: { "Content-Type": "text/html" },
  }), () => {}), /HTTP 504/);
  const validation = await readGenerationResponse(Response.json({
    reference_image: ["Reference image must be JPEG, PNG, or WebP."],
  }, { status: 400 }), () => {});
  assert.equal(validation.success, false);
  assert.match(validation.error, /JPEG, PNG, or WebP/);
});

test("rejects malformed stream events", async () => {
  await assert.rejects(readGenerationResponse(streamResponse("not-json\n"), () => {}), /unreadable response/);
});
