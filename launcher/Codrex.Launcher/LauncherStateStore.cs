using System.IO;
using System.Text.Json;

namespace Codrex.Launcher;

public sealed class LauncherStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = null,
    };

    public LauncherStateStore(string repoRoot)
    {
        RepoRoot = repoRoot;
        RuntimeDir = ResolveRuntimeDir(repoRoot);
        StateDir = Path.Combine(RuntimeDir, "state");
        LogsDir = Path.Combine(RuntimeDir, "logs");
        PreferencesPath = Path.Combine(StateDir, "launcher.state.json");
        LastActionPath = Path.Combine(LogsDir, "last-action.json");
        LastErrorPath = Path.Combine(LogsDir, "last-error.json");
    }

    public string RepoRoot { get; }
    public string RuntimeDir { get; }
    public string StateDir { get; }
    public string LogsDir { get; }
    public string PreferencesPath { get; }
    public string LastActionPath { get; }
    public string LastErrorPath { get; }

    public LauncherPreferences LoadPreferences()
    {
        try
        {
            if (File.Exists(PreferencesPath))
            {
                var raw = File.ReadAllText(PreferencesPath);
                var loaded = JsonSerializer.Deserialize<LauncherPreferences>(raw, JsonOptions);
                if (loaded is not null)
                {
                    loaded.PreferredPairRoute = NormalizeRoute(loaded.PreferredPairRoute);
                    return loaded;
                }
            }
        }
        catch
        {
        }

        return new LauncherPreferences();
    }

    public void SavePreferences(LauncherPreferences preferences)
    {
        Directory.CreateDirectory(StateDir);
        var normalized = new LauncherPreferences
        {
            PreferredPairRoute = NormalizeRoute(preferences.PreferredPairRoute),
            AdvancedVisible = preferences.AdvancedVisible,
        };
        File.WriteAllText(PreferencesPath, JsonSerializer.Serialize(normalized, JsonOptions));
    }

    private static string ResolveRuntimeDir(string repoRoot)
    {
        var overrideValue = (Environment.GetEnvironmentVariable("CODEX_RUNTIME_DIR") ?? string.Empty).Trim();
        if (!string.IsNullOrWhiteSpace(overrideValue))
        {
            return overrideValue;
        }

        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (!string.IsNullOrWhiteSpace(localAppData))
        {
            return Path.Combine(localAppData, "Codrex", "remote-ui");
        }

        return Path.Combine(repoRoot, ".runtime");
    }

    private static string NormalizeRoute(string raw)
    {
        var value = (raw ?? string.Empty).Trim().ToLowerInvariant();
        return value == "tailscale" ? "tailscale" : "lan";
    }
}
