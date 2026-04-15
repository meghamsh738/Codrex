using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Text.RegularExpressions;

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
    public string InstallAutostartScriptPath => Path.Combine(RepoRoot, "tools", "windows", "install-autostart.ps1");
    public string UninstallAutostartScriptPath => Path.Combine(RepoRoot, "tools", "windows", "uninstall-autostart.ps1");

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

    public Task<bool> GetStartupEnabledAsync(CancellationToken cancellationToken = default) =>
        QueryAutostartTaskStateAsync(cancellationToken);

    public Task SetStartupEnabledAsync(bool enabled, CancellationToken cancellationToken = default) =>
        InvokeAutostartScriptAsync(enabled ? InstallAutostartScriptPath : UninstallAutostartScriptPath, cancellationToken);

    public Task<LauncherAccountsPayload?> GetAccountsAsync(bool forceUsage = false, CancellationToken cancellationToken = default) =>
        InvokeAccountToolAsync<LauncherAccountsPayload>(new[]
        {
            "list",
            "--json",
            "--with-usage",
        }.Concat(forceUsage ? new[] { "--force-usage" } : Array.Empty<string>()), cancellationToken);

    public Task<LauncherAccountActivateResult?> ActivateAccountAsync(string accountId, CancellationToken cancellationToken = default) =>
        InvokeAccountToolAsync<LauncherAccountActivateResult>(new[] { "activate", accountId, "--json" }, cancellationToken);

    public async Task<NetInfoPayload?> GetNetInfoAsync(int controllerPort, string token, CancellationToken cancellationToken = default)
    {
        if (controllerPort <= 0)
        {
            return null;
        }

        using var client = BuildHttpClient(token, TimeSpan.FromSeconds(20));
        using var response = await client.GetAsync($"http://127.0.0.1:{controllerPort}/net/info", cancellationToken);
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadAsStringAsync(cancellationToken);
        return JsonSerializer.Deserialize<NetInfoPayload>(payload, JsonOptions);
    }

    public async Task<LauncherPrivacyLockStatus?> GetPrivacyLockStatusAsync(int controllerPort, string token, CancellationToken cancellationToken = default)
    {
        if (controllerPort <= 0)
        {
            return null;
        }

        using var client = BuildHttpClient(token, TimeSpan.FromSeconds(8));
        using var response = await client.GetAsync($"http://127.0.0.1:{controllerPort}/desktop/privacy-lock/status", cancellationToken);
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadAsStringAsync(cancellationToken);
        return JsonSerializer.Deserialize<LauncherPrivacyLockStatus>(payload, JsonOptions);
    }

    public Task<LauncherPrivacyLockStatus?> SavePrivacyPinAsync(int controllerPort, string token, string newPin, string currentPin = "", CancellationToken cancellationToken = default) =>
        PostJsonAsync<LauncherPrivacyLockStatus>(
            controllerPort,
            token,
            "/desktop/privacy-lock/config",
            new { current_pin = currentPin ?? string.Empty, new_pin = newPin ?? string.Empty },
            cancellationToken);

    public Task<LauncherPrivacyLockStatus?> ClearPrivacyPinAsync(int controllerPort, string token, string currentPin = "", CancellationToken cancellationToken = default) =>
        PostJsonAsync<LauncherPrivacyLockStatus>(
            controllerPort,
            token,
            "/desktop/privacy-lock/config",
            new { current_pin = currentPin ?? string.Empty, clear = true },
            cancellationToken);

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
                Detail = DescribeUnavailableRoute(route),
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

    private static TimeSpan GetRuntimeActionTimeout(string action) =>
        action switch
        {
            "start" => TimeSpan.FromSeconds(12),
            "stop" => TimeSpan.FromSeconds(12),
            "repair" => TimeSpan.FromSeconds(8),
            _ => TimeSpan.FromSeconds(5),
        };

    private static bool RuntimeStateSatisfiesAction(string action, RuntimeActionResult? runtime)
    {
        if (runtime is null || !runtime.Ok)
        {
            return false;
        }

        var status = (runtime.Status ?? string.Empty).Trim().ToLowerInvariant();
        return action switch
        {
            "start" => status == "running" || (runtime.ControllerPort > 0 && runtime.SessionPresent && status is "checking" or "recovering"),
            "stop" => status == "stopped",
            "repair" => status is "running" or "stopped" or "checking" or "recovering",
            _ => true,
        };
    }

    private async Task<RuntimeActionResult?> WaitForRuntimeGoalAsync(string action, CancellationToken cancellationToken)
    {
        var deadline = DateTime.UtcNow + (action == "start" ? TimeSpan.FromSeconds(8) : TimeSpan.FromSeconds(6));
        while (DateTime.UtcNow < deadline)
        {
            RuntimeActionResult status;
            try
            {
                status = await GetStatusAsync(cancellationToken);
            }
            catch
            {
                status = null!;
            }

            if (RuntimeStateSatisfiesAction(action, status))
            {
                status.Action = action;
                if (string.IsNullOrWhiteSpace(status.Detail))
                {
                    status.Detail = action == "start"
                        ? "Codrex app stack started."
                        : action == "stop"
                            ? "Codrex app stack stopped."
                            : "Codrex runtime is healthy.";
                }
                return status;
            }

            await Task.Delay(500, cancellationToken);
        }

        return null;
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
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        ConfigurePowerShellStartInfo(startInfo);
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
        var waitForExitTask = process.WaitForExitAsync(cancellationToken);
        var timeout = GetRuntimeActionTimeout(action);
        var completedTask = await Task.WhenAny(waitForExitTask, Task.Delay(timeout, cancellationToken));
        if (completedTask != waitForExitTask)
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                }
            }
            catch
            {
            }

            var recovered = await WaitForRuntimeGoalAsync(action, cancellationToken);
            if (recovered is not null)
            {
                return recovered;
            }

            throw new TimeoutException($"Codrex runtime action '{action}' timed out after {timeout.TotalSeconds:0} seconds.");
        }

        await waitForExitTask;

        var stdout = stdoutTask.ToString();
        var stderr = stderrTask.ToString();
        var payload = ParseRuntimePayload(stdout);
        if (payload is null)
        {
            var recovered = await WaitForRuntimeGoalAsync(action, cancellationToken);
            if (recovered is not null)
            {
                return recovered;
            }
            throw new InvalidOperationException(
                $"Codrex runtime did not return JSON for '{action}'. Stdout: {stdout.Trim()} Stderr: {stderr.Trim()}");
        }

        if (action is "start" or "stop")
        {
            var runtimeLooksGood = RuntimeStateSatisfiesAction(action, payload);
            if (!runtimeLooksGood || process.ExitCode != 0)
            {
                var recovered = await WaitForRuntimeGoalAsync(action, cancellationToken);
                if (recovered is not null)
                {
                    return recovered;
                }
            }
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

    private async Task<T?> InvokeAccountToolAsync<T>(IEnumerable<string> args, CancellationToken cancellationToken)
    {
        var accountToolPath = ToWslPath(Path.Combine(RepoRoot, "tools", "wsl", "codex-account.py"));
        var commandParts = new List<string> { QuoteForBash(accountToolPath) };
        commandParts.AddRange(args.Select(QuoteForBash));
        var bashCommand = string.Join(" ", commandParts);

        var startInfo = new ProcessStartInfo("wsl.exe")
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add("bash");
        startInfo.ArgumentList.Add("-lc");
        startInfo.ArgumentList.Add(bashCommand);

        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        if (!process.Start())
        {
            throw new InvalidOperationException("Could not start WSL account helper.");
        }

        var stdout = await process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = await process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);

        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderr) ? stdout.Trim() : stderr.Trim();
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(detail) ? "WSL account helper failed." : detail);
        }

        var payload = stdout.Trim();
        if (string.IsNullOrWhiteSpace(payload))
        {
            return default;
        }

        return JsonSerializer.Deserialize<T>(payload, JsonOptions);
    }

    private static string QuoteForBash(string value)
    {
        var raw = value ?? string.Empty;
        return $"'{raw.Replace("'", "'\"'\"'")}'";
    }

    private static string ToWslPath(string windowsPath)
    {
        var raw = Path.GetFullPath(windowsPath).Replace('\\', '/');
        var match = Regex.Match(raw, @"^(?<drive>[A-Za-z]):(?<rest>/.*)?$");
        if (!match.Success)
        {
            return raw;
        }

        var drive = match.Groups["drive"].Value.ToLowerInvariant();
        var rest = match.Groups["rest"].Value;
        return string.IsNullOrWhiteSpace(rest) ? $"/mnt/{drive}" : $"/mnt/{drive}{rest}";
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

    private static HttpClient BuildHttpClient(string token, TimeSpan? timeout = null)
    {
        var client = new HttpClient
        {
            Timeout = timeout ?? TimeSpan.FromSeconds(10),
        };
        if (!string.IsNullOrWhiteSpace(token))
        {
            client.DefaultRequestHeaders.Add("x-auth-token", token);
        }
        return client;
    }

    private static string ResolveRouteHost(string route, NetInfoPayload netInfo, RuntimeActionResult runtime)
    {
        var normalized = (route ?? string.Empty).Trim().ToLowerInvariant();
        if (string.Equals(normalized, "preferred", StringComparison.OrdinalIgnoreCase))
        {
            var preferredHost = ExtractHostFromOrigin(netInfo.PreferredOrigin);
            if (!string.IsNullOrWhiteSpace(preferredHost))
            {
                return preferredHost;
            }
        }

        if (string.Equals(normalized, "tailscale", StringComparison.OrdinalIgnoreCase))
        {
            return string.IsNullOrWhiteSpace(netInfo.TailscaleIp) ? "" : netInfo.TailscaleIp.Trim();
        }

        if (string.Equals(normalized, "netbird", StringComparison.OrdinalIgnoreCase))
        {
            return string.IsNullOrWhiteSpace(netInfo.NetbirdIp) ? "" : netInfo.NetbirdIp.Trim();
        }

        if (string.Equals(normalized, "current", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(runtime.NetworkUrl))
        {
            try
            {
                return new Uri(runtime.NetworkUrl).Host;
            }
            catch
            {
            }
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

    private static string ExtractHostFromOrigin(string origin)
    {
        if (string.IsNullOrWhiteSpace(origin))
        {
            return "";
        }

        try
        {
            return new Uri(origin).Host;
        }
        catch
        {
            return "";
        }
    }

    private static string DescribeUnavailableRoute(string route)
    {
        return (route ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "tailscale" => "Tailscale is unavailable on this laptop.",
            "netbird" => "NetBird is unavailable on this laptop.",
            "current" => "The current route is unavailable on this laptop.",
            "preferred" => "No private route is available on this laptop yet.",
            _ => "LAN IP is unavailable on this laptop.",
        };
    }

    private static async Task<T?> PostJsonAsync<T>(
        int controllerPort,
        string token,
        string path,
        object payload,
        CancellationToken cancellationToken)
    {
        if (controllerPort <= 0)
        {
            return default;
        }

        using var client = BuildHttpClient(token, TimeSpan.FromSeconds(8));
        var raw = JsonSerializer.Serialize(payload);
        using var response = await client.PostAsync(
            $"http://127.0.0.1:{controllerPort}{path}",
            new StringContent(raw, Encoding.UTF8, "application/json"),
            cancellationToken);
        var content = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            try
            {
                var errorPayload = JsonSerializer.Deserialize<Dictionary<string, object>>(content, JsonOptions);
                var detail = errorPayload is not null && errorPayload.TryGetValue("detail", out var detailValue)
                    ? Convert.ToString(detailValue) ?? string.Empty
                    : string.Empty;
                throw new InvalidOperationException(string.IsNullOrWhiteSpace(detail) ? $"Request failed with HTTP {(int)response.StatusCode}." : detail);
            }
            catch (JsonException)
            {
                throw new InvalidOperationException(string.IsNullOrWhiteSpace(content) ? $"Request failed with HTTP {(int)response.StatusCode}." : content.Trim());
            }
        }
        if (string.IsNullOrWhiteSpace(content))
        {
            return default;
        }
        return JsonSerializer.Deserialize<T>(content, JsonOptions);
    }

    private async Task<bool> QueryAutostartTaskStateAsync(CancellationToken cancellationToken)
    {
        const string startupTaskName = "CodrexRemoteController.Startup";
        const string watchdogTaskName = "CodrexRemoteController.Watchdog";
        const string launcherTaskName = "CodrexLauncher.Tray";
        const string script = @"
$startup = Get-ScheduledTask -TaskName 'CodrexRemoteController.Startup' -ErrorAction SilentlyContinue
$watchdog = Get-ScheduledTask -TaskName 'CodrexRemoteController.Watchdog' -ErrorAction SilentlyContinue
$launcher = Get-ScheduledTask -TaskName 'CodrexLauncher.Tray' -ErrorAction SilentlyContinue
if ($startup -and $watchdog -and $launcher) { 'true' } else { 'false' }
";
        var result = await InvokePowerShellAsync(script, cancellationToken);
        if (result.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(result.Stderr) ? result.Stdout.Trim() : result.Stderr.Trim();
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(detail)
                ? $"Could not query startup tasks '{startupTaskName}', '{watchdogTaskName}', and '{launcherTaskName}'."
                : detail);
        }
        return string.Equals(result.Stdout.Trim(), "true", StringComparison.OrdinalIgnoreCase);
    }

    private async Task InvokeAutostartScriptAsync(string scriptPath, CancellationToken cancellationToken)
    {
        if (!File.Exists(scriptPath))
        {
            throw new FileNotFoundException("Autostart helper script is missing.", scriptPath);
        }

        var result = await InvokePowerShellFileAsync(scriptPath, cancellationToken);
        if (result.ExitCode == 0)
        {
            return;
        }

        var detail = string.IsNullOrWhiteSpace(result.Stderr) ? result.Stdout.Trim() : result.Stderr.Trim();
        throw new InvalidOperationException(string.IsNullOrWhiteSpace(detail) ? "Autostart update failed." : detail);
    }

    private Task<PowerShellInvocationResult> InvokePowerShellFileAsync(string scriptPath, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo("powershell.exe")
        {
            WorkingDirectory = RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        ConfigurePowerShellStartInfo(startInfo);
        startInfo.ArgumentList.Add("-File");
        startInfo.ArgumentList.Add(scriptPath);
        return InvokePowerShellProcessAsync(startInfo, cancellationToken);
    }

    private Task<PowerShellInvocationResult> InvokePowerShellAsync(string script, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo("powershell.exe")
        {
            WorkingDirectory = RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        ConfigurePowerShellStartInfo(startInfo);
        startInfo.ArgumentList.Add("-Command");
        startInfo.ArgumentList.Add(script);
        return InvokePowerShellProcessAsync(startInfo, cancellationToken);
    }

    private static void ConfigurePowerShellStartInfo(ProcessStartInfo startInfo)
    {
        startInfo.ArgumentList.Add("-NoLogo");
        startInfo.ArgumentList.Add("-NoProfile");
        startInfo.ArgumentList.Add("-NonInteractive");
        startInfo.ArgumentList.Add("-WindowStyle");
        startInfo.ArgumentList.Add("Hidden");
        startInfo.ArgumentList.Add("-ExecutionPolicy");
        startInfo.ArgumentList.Add("Bypass");
    }

    private static async Task<PowerShellInvocationResult> InvokePowerShellProcessAsync(ProcessStartInfo startInfo, CancellationToken cancellationToken)
    {
        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        if (!process.Start())
        {
            throw new InvalidOperationException("Could not start PowerShell.");
        }

        var stdout = await process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = await process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        return new PowerShellInvocationResult(process.ExitCode, stdout, stderr);
    }

    private readonly record struct PowerShellInvocationResult(int ExitCode, string Stdout, string Stderr);
}
