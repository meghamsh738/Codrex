import { describe, expect, it } from "vitest";
import { DESKTOP_PROFILE_STREAM, resolveDesktopStreamParams } from "../desktopStream";

describe("resolveDesktopStreamParams", () => {
  it("keeps the base profile when adaptive mode is off", () => {
    expect(
      resolveDesktopStreamParams("balanced", {
        active: true,
        fullscreen: true,
        adaptiveBoost: false,
      }),
    ).toEqual(DESKTOP_PROFILE_STREAM.balanced);
  });

  it("boosts fullscreen active remotes without changing profile intent", () => {
    expect(
      resolveDesktopStreamParams("saver", {
        active: true,
        fullscreen: true,
        adaptiveBoost: true,
      }),
    ).toEqual({
      fps: 6,
      level: 2,
      scale: 2,
      bw: false,
    });
  });

  it("throttles inactive remotes to save host work", () => {
    expect(
      resolveDesktopStreamParams("responsive", {
        active: false,
        fullscreen: false,
        adaptiveBoost: true,
      }),
    ).toEqual({
      fps: 2,
      level: 2,
      scale: 2,
      bw: false,
    });
  });
});

