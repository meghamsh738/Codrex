import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applySessionProfile,
  buildPairConsumeUrl,
  buildPairQrPngUrl,
  buildSuggestedControllerUrl,
  createSharedFile,
  deleteSharedFile,
  listSharedFiles,
} from "../api";

describe("pairing URL helpers", () => {
  it("builds consume link from plain host", () => {
    const url = buildPairConsumeUrl("192.168.1.2:8787", "abc123");
    expect(url).toBe("http://192.168.1.2:8787/auth/pair/consume?code=abc123");
  });

  it("builds qr URL with encoded data", () => {
    const target = "http://10.0.0.10:8787/auth/pair/consume?code=xyz";
    const qr = buildPairQrPngUrl("http://10.0.0.10:8787", target);
    expect(qr).toBe(
      "http://10.0.0.10:8787/auth/pair/qr.png?data=http%3A%2F%2F10.0.0.10%3A8787%2Fauth%2Fpair%2Fconsume%3Fcode%3Dxyz",
    );
  });
});

describe("base URL suggestions", () => {
  it("prefers LAN route when available", () => {
    const suggested = buildSuggestedControllerUrl(
      "127.0.0.1",
      8787,
      { ok: true, lan_ip: "192.168.1.120", tailscale_ip: "" },
      "lan",
    );
    expect(suggested).toBe("http://192.168.1.120:8787");
  });

  it("falls back to LAN when tailscale route is selected but unavailable", () => {
    const suggested = buildSuggestedControllerUrl(
      "localhost",
      8787,
      { ok: true, lan_ip: "192.168.1.120", tailscale_ip: "" },
      "tailscale",
    );
    expect(suggested).toBe("http://192.168.1.120:8787");
  });

  it("falls back to current host", () => {
    const suggested = buildSuggestedControllerUrl("localhost", 8787, null, "tailscale");
    expect(suggested).toBe("http://localhost:8787");
  });
});

describe("session profile apply API", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("posts model + reasoning payload to profile endpoint", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true }),
    });

    const out = await applySessionProfile("codex_demo", {
      model: "gpt-5",
      reasoning_effort: "xhigh",
    });

    expect(out.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/codex/session/codex_demo/profile",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "gpt-5",
          reasoning_effort: "xhigh",
        }),
      }),
    );
  });
});

describe("shared files API", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("lists shared files", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true, items: [] }),
    });
    const out = await listSharedFiles();
    expect(out.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/shares",
      expect.objectContaining({
        credentials: "include",
      }),
    );
  });

  it("creates shared file with payload", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true, item: { id: "shr_1" } }),
    });
    const out = await createSharedFile({
      path: "/home/megha/codrex-work/out/image.png",
      title: "Image",
      expires_hours: 24,
      created_by: "session:codex_demo",
    });
    expect(out.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/shares",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: "/home/megha/codrex-work/out/image.png",
          title: "Image",
          expires_hours: 24,
          created_by: "session:codex_demo",
        }),
      }),
    );
  });

  it("deletes shared file by id", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true }),
    });
    const out = await deleteSharedFile("shr_123");
    expect(out.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/shares/shr_123", expect.objectContaining({ method: "DELETE" }));
  });
});
