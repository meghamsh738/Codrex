using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace Codrex.Launcher;

public sealed class LauncherRuntimeService
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public LauncherRuntimeService(string repoRoot, LauncherStateStore stateStore)
    {
        RepoRoot = repoRoot;
        StateStore = stateStore;
        RuntimeScriptPath = Path.Combine(repoRoot, "tools", "windows", "codrex-runtime.ps1");
        ConfigPath = Path.Combine(repoRoot, "controller.config.json");
        LocalConfigPath = Path.Combine(StateStore.StateDir, "controller.config.local.json");
    }

    public string RepoRoot { get; }
    public LauncherStateStore StateStore { get; }
    public string RuntimeScriptPath { get; }
    public string ConfigPath { get; }
    public string LocalConfigPath { get; }

    public static string FindRepoRoot()
    {
        var candidates = new List<string>();
        var cwd = Directory.GetCurrentDirectory();
        if (!string.IsNullOrWhiteSpace(cwd))
        {
            candidates.Add(cwd);
        }

        var baseDir = AppContext.BaseDirectory;
        if (!string.IsNullOrWhiteSpace(baseDir))
        {
            candidates.Add(baseDir);
            candidates.Add(Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..")));
            candidates.Add(Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "..")));
        }

        foreach (var candidate in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            var runtimeScript = Path.Combine(candidate, "tools", "windows", "codrex-runtime.ps1");
            if (File.Exists(runtimeScript))
            {
                return Path.GetFullPath(candidate);
            }
        }

        throw new InvalidOperationException("Could not locate the Codrex repo root from the launcher executable.");
    }

    public Task<RuntimeActionResult> GetStatusAsync(CancellationToken cancellationToken = default) =>
        InvokeRuntimeAsync("status", cancellationToken);

    public Task<RuntimeActionResult> StartAsync(CancellationToken cancellationToken = default) =>
        InvokeRuntimeAsync("start", cancellationToken);

    public Task<RuntimeActionResult> StopAsync(CancellationToken cancellationToken = default) =>
        InvokeRuntimeAsync("stop", cancellationToken);

    public Task<RuntimeActionResult> RepairAsync(CancellationToken cancellationToken = default) =>
        InvokeRuntimeAsync("repair", cancellationToken);

    public async Task<NetInfoPayload?> GetNetInfoAsync(int controllerPort, string token, CancellationToken cancellationToken = default)
    {
        if (controllerPort <= 0)
        {
            return null;
        }

        using var client = BuildHttpClient(token);
        using var response = await client.GetAsync($"http://127.0.0.1:{controllerPort}/net/info", cancellationToken);
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadAsStringAsync(cancellationToken);
        return JsonSerializer.Deserialize<NetInfoPayload>(payload, JsonOptions);
    }

    public async Task<PairingResult> CreatePairingAsync(RuntimeActionResult runtime, string route, CancellationToken cancellationToken = default)
    {
        if (!runtime.Ok || runtime.ControllerPort <= 0)
        {
            return new PairingResult
            {
                Ok = false,
                Detail = "Start Codrex before generating a pairing QR.",
            };
        }

        var config = ReadControllerConfig();
        var token = config.Token;
        using var client = BuildHttpClient(token);
        using var response = await client.PostAsync($"http://127.0.0.1:{runtime.ControllerPort}/auth/pair/create", new StringContent("{}", Encoding.UTF8, "application/json"), cancellationToken);
        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        var payload = JsonSerializer.Deserialize<PairCreatePayload>(raw, JsonOptions) ?? new PairCreatePayload();
        if (!response.IsSuccessStatusCode || !payload.Ok)
        {
            return new PairingResult
            {
                Ok = false,
                Detail = payload.Detail?.Trim() is { Length: > 0 } detail
                    ? detail
                    : payload.Error?.Trim() is { Length: > 0 } error
                        ? error
                        : "Could not generate pairing code.",
            };
        }

        if (string.IsNullOrWhiteSpace(payload.Code))
        {
            return new PairingResult
            {
                Ok = true,
                Detail = "Auth token is disabled; pairing QR is not required.",
            };
        }

        var netInfo = await GetNetInfoAsync(runtime.ControllerPort, token, cancellationToken) ?? new NetInfoPayload();
        var routeHost = ResolveRouteHost(route, netInfo, runtime);
        if (string.IsNullOrWhiteSpace(routeHost))
        {
            return new PairingResult
            {
                Ok = false,
                Detail = route == "tailscale"
                    ? "Tailscale is unavailable on this laptop."
                    : "LAN IP is unavailable on this laptop.",
            };
        }

        var pairLink = $"http://{routeHost}:{runtime.ControllerPort}/auth/pair/consume?code={Uri.EscapeDataString(payload.Code)}";
        var qrUrl = $"http://127.0.0.1:{runtime.ControllerPort}/auth/pair/qr.png?data={Uri.EscapeDataString(pairLink)}";
        return new PairingResult
        {
            Ok = true,
            Detail = $"Pairing QR ready for {route}.",
            PairLink = pairLink,
            QrImageUrl = qrUrl,
            ExpiresIn = payload.ExpiresIn,
        };
    }

    public ControllerConfigData ReadControllerConfig()
    {
        var merged = new ControllerConfigData();
        foreach (var candidate in new[] { ConfigPath, LocalConfigPath })
        {
            try
            {
                if (!File.Exists(candidate))
                {
                    continue;
                }

                var raw = File.ReadAllText(candidate);
                var data = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(raw, JsonOptions);
                if (data is null)
                {
                    continue;
                }

                if (data.TryGetValue("port", out var portElement) && portElement.ValueKind == JsonValueKind.Number && portElement.TryGetInt32(out var port))
                {
                    merged.Port = port;
                }
                if (data.TryGetValue("token", out var tokenElement) && tokenElement.ValueKind == JsonValueKind.String)
                {
                    var token = tokenElement.GetString();
                    if (!string.IsNullOrWhiteSpace(token))
                    {
                        merged.Token = token.Trim();
                    }
                }
            }
            catch
            {
            }
        }

        return merged;
    }

    public string? ReadLastErrorPath()
    {
        return File.Exists(StateStore.LastErrorPath) ? StateStore.LastErrorPath : null;
    }

    public string? ReadLastActionPath()
    {
        return File.Exists(StateStore.LastActionPath) ? StateStore.LastActionPath : null;
    }

    private async Task<RuntimeActionResult> InvokeRuntimeAsync(string action, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo("powershell.exe")
        {
            WorkingDirectory = RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add("-NoProfile");
        startInfo.ArgumentList.Add("-ExecutionPolicy");
        startInfo.ArgumentList.Add("Bypass");
        startInfo.ArgumentList.Add("-File");
        startInfo.ArgumentList.Add(RuntimeScriptPath);
        startInfo.ArgumentList.Add("-Action");
        startInfo.ArgumentList.Add(action);

        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        var stdoutTask = new StringBuilder();
        var stderrTask = new StringBuilder();
        process.OutputDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                stdoutTask.AppendLine(args.Data);
            }
        };
        process.ErrorDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                stderrTask.AppendLine(args.Data);
            }
        };

        if (!process.Start())
        {
            throw new InvalidOperationException($"Could not start runtime action '{action}'.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync(cancellationToken);

        var stdout = stdoutTask.ToString();
        var stderr = stderrTask.ToString();
        var payload = ParseRuntimePayload(stdout);
        if (payload is null)
        {
            throw new InvalidOperationException(
                $"Codrex runtime did not return JSON for '{action}'. Stdout: {stdout.Trim()} Stderr: {stderr.Trim()}");
        }

        if (process.ExitCode != 0)
        {
            payload.Ok = false;
            if (string.IsNullOrWhiteSpace(payload.Detail))
            {
                payload.Detail = stderr.Trim();
            }
        }
        return payload;
    }

    private static RuntimeActionResult? ParseRuntimePayload(string stdout)
    {
        var lines = stdout
            .Split(new[] { "\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries)
            .Reverse();
        foreach (var line in lines)
        {
            try
            {
                return JsonSerializer.Deserialize<RuntimeActionResult>(line, JsonOptions);
            }
            catch
            {
            }
        }
        return null;
    }

    private static HttpClient BuildHttpClient(string token)
    {
        var client = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(10),
        };
        if (!string.IsNullOrWhiteSpace(token))
        {
            client.DefaultRequestHeaders.Add("x-auth-token", token);
        }
        return client;
    }

    private static string ResolveRouteHost(string route, NetInfoPayload netInfo, RuntimeActionResult runtime)
    {
        if (string.Equals(route, "tailscale", StringComparison.OrdinalIgnoreCase))
        {
            return string.IsNullOrWhiteSpace(netInfo.TailscaleIp) ? "" : netInfo.TailscaleIp.Trim();
        }

        if (!string.IsNullOrWhiteSpace(netInfo.LanIp))
        {
            return netInfo.LanIp.Trim();
        }

        if (!string.IsNullOrWhiteSpace(runtime.NetworkUrl))
        {
            try
            {
                return new Uri(runtime.NetworkUrl).Host;
            }
            catch
            {
            }
        }

        return "";
    }
}
