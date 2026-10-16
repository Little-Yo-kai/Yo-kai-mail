export type GenerationEvent<T> = {
  type?: "started" | "progress" | "heartbeat" | "result" | "error";
  success?: boolean;
  stage?: string;
  error?: string;
  request_id?: string;
  timeout_seconds?: number;
  data?: T;
};

function responseError(payload: Record<string, unknown>, status: number) {
  if (typeof payload.error === "string") return payload.error;
  // DRF validation errors use field names rather than an `error` property.
  for (const field of ["url", "reference_image", "additional_instructions", "detail"]) {
    const value = payload[field];
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.join(" ");
  }
  return `The generation service returned HTTP ${status}. Please try again.`;
}

export async function readGenerationResponse<T>(
  response: Response,
  onEvent: (event: GenerationEvent<T>) => void,
): Promise<GenerationEvent<T>> {
  if (!response.ok || !response.headers.get("content-type")?.includes("application/x-ndjson")) {
    let payload: GenerationEvent<T> & Record<string, unknown>;
    try {
      payload = await response.json();
    } catch {
      throw new Error(`The generation service returned HTTP ${response.status}. Please check the backend and try again.`);
    }
    if (!response.ok || !payload.success) {
      return { ...payload, success: false, error: responseError(payload, response.status) };
    }
    return payload;
  }

  if (!response.body) throw new Error("The server did not provide a generation response.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      if (done && pending.trim()) lines.push(pending);
      for (const line of lines) {
        if (!line.trim()) continue;
        let event: GenerationEvent<T>;
        try {
          event = JSON.parse(line);
        } catch {
          throw new Error("The generation connection returned an unreadable response. Please try again.");
        }
        if (!event || typeof event !== "object") {
          throw new Error("The generation connection returned an unreadable response. Please try again.");
        }
        onEvent(event);
        if (event.type === "result" || event.type === "error") return event;
      }
      if (done) break;
    }
    throw new Error("The connection ended before the email was ready. Please try again.");
  } finally {
    // Also close a response if a terminal event arrived before network EOF.
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
