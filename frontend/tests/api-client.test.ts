import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  clearApiAuthToken,
  issueApiAuthToken,
  request,
  setApiAuthToken
} from "@/lib/api/client";

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

  it("raises ApiError for backend authentication failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Authentication required." }), {
          status: 401,
          headers: { "Content-Type": "application/json" }
        })
      )
    );

    await expect(request("/analyses")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Authentication required."
    } satisfies Partial<ApiError>);
  });

  it("raises ApiError for backend authorization failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Forbidden." }), {
          status: 403,
          headers: { "Content-Type": "application/json" }
        })
      )
    );

    await expect(request("/analyses/id/review")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: "Forbidden."
    } satisfies Partial<ApiError>);
  });

  it("issues and stores a signed bearer token", async () => {
    setApiAuthToken("old-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: {
            access_token: "signed-token",
            token_type: "bearer",
            expires_in: 3600,
            subject: "demo",
            role: "admin"
          },
          meta: {},
          error: null
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const issued = await issueApiAuthToken({ username: "demo", password: "secret" });

    expect(issued.access_token).toBe("signed-token");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/token");
    expect((init.headers as HeadersInit as Record<string, string>).Authorization).toBeUndefined();

    const protectedFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { ok: true }, meta: {}, error: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", protectedFetch);
    await request<{ ok: boolean }>("/companies");
    const protectedInit = protectedFetch.mock.calls[0][1] as RequestInit;
    expect((protectedInit.headers as Headers).get("Authorization")).toBe("Bearer signed-token");
  });

  it("clears bearer token from browser storage", async () => {
    setApiAuthToken("token-123");
    clearApiAuthToken();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { ok: true }, meta: {}, error: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await request<{ ok: boolean }>("/companies");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Headers).get("Authorization")).toBeNull();
  });
});
