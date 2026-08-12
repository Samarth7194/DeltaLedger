import { afterEach, describe, expect, it, vi } from "vitest";

import { clearApiAuthToken, request, setApiAuthToken } from "@/lib/api/client";

describe("api client auth", () => {
  afterEach(() => {
    clearApiAuthToken();
    vi.restoreAllMocks();
  });

  it("attaches bearer token from browser storage when present", async () => {
    setApiAuthToken("token-123");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { ok: true }, meta: {}, error: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/companies");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toContain("/companies");
    expect(init.headers).toBeInstanceOf(Headers);
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer token-123");
  });
});
