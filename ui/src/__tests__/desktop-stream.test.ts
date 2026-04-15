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
      scale: 3,
      bw: false,
    });
  });

  it("biases the responsive profile toward lighter default mobile frames", () => {
    expect(DESKTOP_PROFILE_STREAM.responsive).toEqual({
      fps: 10,
      level: 1,
      scale: 2,
      bw: false,
    });

    expect(
      resolveDesktopStreamParams("responsive", {
        active: true,
        fullscreen: true,
        adaptiveBoost: true,
      }),
    ).toEqual({
      fps: 12,
      level: 0,
      scale: 1,
      bw: false,
    });
  });
});
