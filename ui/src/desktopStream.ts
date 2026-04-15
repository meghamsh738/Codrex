export type DesktopStreamProfile = "responsive" | "balanced" | "saver" | "ultra" | "extreme";

export interface DesktopStreamParams {
  fps: number;
  level: number;
  scale: number;
  bw: boolean;
}

export interface DesktopStreamTuningOptions {
  active?: boolean;
  fullscreen?: boolean;
  adaptiveBoost?: boolean;
}

export const DESKTOP_PROFILE_STREAM: Record<DesktopStreamProfile, DesktopStreamParams> = {
  responsive: { fps: 10, level: 1, scale: 2, bw: false },
  balanced: { fps: 6, level: 2, scale: 2, bw: false },
  saver: { fps: 4, level: 3, scale: 3, bw: false },
  ultra: { fps: 3, level: 2, scale: 3, bw: true },
  extreme: { fps: 2, level: 3, scale: 4, bw: true },
};

const DESKTOP_FULLSCREEN_BOOST: Record<DesktopStreamProfile, DesktopStreamParams> = {
  responsive: { fps: 12, level: 0, scale: 1, bw: false },
  balanced: { fps: 8, level: 1, scale: 1, bw: false },
  saver: { fps: 6, level: 2, scale: 2, bw: false },
  ultra: { fps: 5, level: 2, scale: 2, bw: true },
  extreme: { fps: 4, level: 3, scale: 3, bw: true },
};

export function resolveDesktopStreamParams(
  profile: DesktopStreamProfile,
  options?: DesktopStreamTuningOptions,
): DesktopStreamParams {
  const base = DESKTOP_PROFILE_STREAM[profile];
  if (!base) {
    return DESKTOP_PROFILE_STREAM.responsive;
  }
  if (!options?.adaptiveBoost) {
    return { ...base };
  }
  if (options.fullscreen && options.active) {
    return { ...DESKTOP_FULLSCREEN_BOOST[profile] };
  }
  if (!options.active) {
    return {
      fps: Math.min(base.fps, 2),
      level: Math.min(4, base.level + 1),
      scale: Math.min(4, base.scale + 1),
      bw: base.bw,
    };
  }
  return { ...base };
}
