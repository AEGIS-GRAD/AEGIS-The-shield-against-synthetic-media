// @vitest-environment node
import { describe, it, expect } from "vitest";
import { GET } from "../route";

describe("API Route /api/health (W12)", () => {
  it("returns healthy status with service identifier and valid ISO timestamp", async () => {
    const res = await GET();
    expect(res.status).toBe(200);

    const body = await res.json();
    expect(body.status).toBe("healthy");
    expect(body.service).toBe("aegis-web");
    expect(() => new Date(body.timestamp).toISOString()).not.toThrow();
    expect(Number.isNaN(Date.parse(body.timestamp))).toBe(false);
  });
});

