using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;

namespace Codrex.Launcher;

public partial class MainWindow : Window
{
    private readonly LauncherRuntimeService _runtimeService;
    private readonly LauncherStateStore _stateStore;
    private readonly DispatcherTimer _refreshTimer;
    private readonly LauncherPreferences _preferences;
    private RuntimeActionResult? _lastRuntime;
    private PairingResult? _currentPairing;
    private NetInfoPayload? _lastNetInfo;
    private bool _webReady;
    private bool _actionBusy;
    private long _actionGeneration;
    private string _pendingAction = "";
    private string _statusDetail = "Launcher ready.";
    private string _errorDetail = "";

    public MainWindow()
    {
        InitializeComponent();
        var repoRoot = LauncherRuntimeService.FindRepoRoot();
        _stateStore = new LauncherStateStore(repoRoot);
        _runtimeService = new LauncherRuntimeService(repoRoot, _stateStore);
        _preferences = _stateStore.LoadPreferences();
        _refreshTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(1.25),
        };
        _refreshTimer.Tick += async (_, _) => await RefreshStateAsync();
        Loaded += async (_, _) => await InitializeLauncherAsync();
        Closed += (_, _) => _refreshTimer.Stop();
    }

    private async Task InitializeLauncherAsync()
    {
        try
        {
            await LauncherView.EnsureCoreWebView2Async();
            LauncherView.CoreWebView2.WebMessageReceived += OnWebMessageReceived;
            LauncherView.NavigationCompleted += async (_, _) =>
            {
                _webReady = true;
                await PublishStateAsync();
            };
            var html = await LoadLauncherHtmlAsync();
            LauncherView.NavigateToString(html);
            _refreshTimer.Start();
            await RefreshStateAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                $"Codrex desktop launcher could not initialize WebView2.\n\n{ex.Message}",
                "Codrex Launcher",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Close();
        }
    }

    private async void OnWebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            using var document = JsonDocument.Parse(e.WebMessageAsJson);
            var root = document.RootElement;
            var type = root.TryGetProperty("type", out var typeProperty) ? typeProperty.GetString() ?? "" : "";
            switch (type)
            {
                case "ready":
                    await PublishStateAsync();
                    break;
                case "start":
                    await RunRuntimeActionAsync("start");
                    break;
                case "stop":
                    await RunRuntimeActionAsync("stop");
                    break;
                case "route":
                    if (root.TryGetProperty("route", out var routeProperty))
                    {
                        var route = NormalizeRoute(routeProperty.GetString());
                        _preferences.PreferredPairRoute = route;
                        _stateStore.SavePreferences(_preferences);
                        _currentPairing = null;
                        _statusDetail = $"Selected {route} route.";
                        await PublishStateAsync();
                    }
                    break;
                case "toggleAdvanced":
                    _preferences.AdvancedVisible = !_preferences.AdvancedVisible;
                    _stateStore.SavePreferences(_preferences);
                    await PublishStateAsync();
                    break;
                case "showQr":
                    await GeneratePairingAsync();
                    break;
                case "openApp":
                    if (_lastRuntime is { Ok: true } runtime && !string.IsNullOrWhiteSpace(runtime.LocalUrl))
                    {
                        OpenUrl(runtime.LocalUrl);
                        _statusDetail = $"Opened app: {runtime.LocalUrl}";
                        _errorDetail = "";
                        await PublishStateAsync();
                    }
                    break;
                case "openNetworkApp":
                    var networkUrl = BuildSelectedNetworkUrl();
                    if (!string.IsNullOrWhiteSpace(networkUrl))
                    {
                        OpenUrl(networkUrl);
                        _statusDetail = $"Opened network app: {networkUrl}";
                        _errorDetail = "";
                        await PublishStateAsync();
                    }
                    break;
                case "openFallback":
                    if (_lastRuntime is { Ok: true } runtimeFallback && !string.IsNullOrWhiteSpace(runtimeFallback.LocalUrl))
                    {
                        var fallbackUrl = $"{runtimeFallback.LocalUrl.TrimEnd('/')}/legacy";
                        OpenUrl(fallbackUrl);
                        _statusDetail = $"Opened fallback: {fallbackUrl}";
                        _errorDetail = "";
                        await PublishStateAsync();
                    }
                    break;
                case "copyPairLink":
                    if (!string.IsNullOrWhiteSpace(_currentPairing?.PairLink))
                    {
                        Clipboard.SetText(_currentPairing.PairLink);
                        _statusDetail = "Copied pairing link.";
                        _errorDetail = "";
                        await PublishStateAsync();
                    }
                    break;
                case "copyLogPath":
                    Clipboard.SetText(_stateStore.LogsDir);
                    _statusDetail = "Copied logs path.";
                    _errorDetail = "";
                    await PublishStateAsync();
                    break;
                case "copyLastError":
                    if (File.Exists(_stateStore.LastErrorPath))
                    {
                        Clipboard.SetText(_stateStore.LastErrorPath);
                        _statusDetail = "Copied last error path.";
                        _errorDetail = "";
                        await PublishStateAsync();
                    }
                    break;
                case "openLogs":
                    OpenDirectory(_stateStore.LogsDir);
                    _statusDetail = "Opened Codrex logs.";
                    _errorDetail = "";
                    await PublishStateAsync();
                    break;
            }
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
            await PublishStateAsync();
        }
    }

    private static async Task<string> LoadLauncherHtmlAsync()
    {
        const string resourceName = "Codrex.Launcher.Assets.launcher.html";
        await using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(resourceName)
            ?? throw new InvalidOperationException($"Missing embedded launcher asset: {resourceName}");
        using var reader = new StreamReader(stream);
        return await reader.ReadToEndAsync();
    }

    private async Task RunRuntimeActionAsync(string action)
    {
        if (_actionBusy)
        {
            return;
        }

        _actionBusy = true;
        _actionGeneration += 1;
        var generation = _actionGeneration;
        _pendingAction = action;
        _errorDetail = "";
        _currentPairing = action == "stop" ? null : _currentPairing;
        _statusDetail = action == "start" ? "Starting Codrex runtime..." : action == "stop" ? "Stopping Codrex runtime..." : "Running Codrex action...";
        await PublishStateAsync();

        try
        {
            RuntimeActionResult result = action switch
            {
                "start" => await _runtimeService.StartAsync(),
                "stop" => await _runtimeService.StopAsync(),
                "repair" => await _runtimeService.RepairAsync(),
                _ => await _runtimeService.GetStatusAsync(),
            };

            if (generation != _actionGeneration)
            {
                return;
            }

            _lastRuntime = result;
            if (!result.Ok)
            {
                _errorDetail = string.IsNullOrWhiteSpace(result.Detail) ? $"Codrex {action} failed." : result.Detail;
            }
            else
            {
                _statusDetail = string.IsNullOrWhiteSpace(result.Detail) ? $"Codrex {action} complete." : result.Detail;
                if (action == "stop")
                {
                    _currentPairing = null;
                }
            }
        }
        catch (Exception ex)
        {
            if (generation != _actionGeneration)
            {
                return;
            }
            _errorDetail = ex.Message;
        }
        finally
        {
            if (generation == _actionGeneration)
            {
                _actionBusy = false;
                _pendingAction = "";
                await RefreshStateAsync();
            }
        }
    }

    private async Task GeneratePairingAsync()
    {
        await RefreshStateAsync();
        if (_lastRuntime is null || !_lastRuntime.Ok || string.IsNullOrWhiteSpace(_lastRuntime.Status) || !_lastRuntime.Status.Equals("running", StringComparison.OrdinalIgnoreCase))
        {
            _errorDetail = "Start Codrex before generating a pairing QR.";
            await PublishStateAsync();
            return;
        }

        try
        {
            _currentPairing = await _runtimeService.CreatePairingAsync(_lastRuntime, _preferences.PreferredPairRoute);
            if (_currentPairing.Ok)
            {
                _statusDetail = _currentPairing.Detail;
                _errorDetail = "";
            }
            else
            {
                _errorDetail = _currentPairing.Detail;
            }
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
        }

        await PublishStateAsync();
    }

    private async Task RefreshStateAsync()
    {
        try
        {
            _lastRuntime = await _runtimeService.GetStatusAsync();
            TryCompletePendingActionFromLiveState(_lastRuntime);
            if (_lastRuntime.Ok && _lastRuntime.Status.Equals("running", StringComparison.OrdinalIgnoreCase))
            {
                var config = _runtimeService.ReadControllerConfig();
                _lastNetInfo = await _runtimeService.GetNetInfoAsync(_lastRuntime.ControllerPort, config.Token);
            }
            else
            {
                _lastNetInfo = null;
            }
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
        }

        await PublishStateAsync();
    }

    private void TryCompletePendingActionFromLiveState(RuntimeActionResult? runtime)
    {
        if (!_actionBusy || runtime is null || !runtime.Ok)
        {
            return;
        }

        var status = (runtime.Status ?? string.Empty).Trim().ToLowerInvariant();
        if (_pendingAction == "start" && status == "running")
        {
            _actionGeneration += 1;
            _actionBusy = false;
            _pendingAction = "";
            _errorDetail = "";
            _statusDetail = string.IsNullOrWhiteSpace(runtime.Detail) ? "Codrex start complete." : runtime.Detail;
            return;
        }

        if (_pendingAction == "stop" && status == "stopped")
        {
            _actionGeneration += 1;
            _actionBusy = false;
            _pendingAction = "";
            _errorDetail = "";
            _currentPairing = null;
            _statusDetail = string.IsNullOrWhiteSpace(runtime.Detail) ? "Codrex stop complete." : runtime.Detail;
        }
    }

    private async Task PublishStateAsync()
    {
        if (!_webReady || LauncherView.CoreWebView2 is null)
        {
            return;
        }

        var runtime = _lastRuntime ?? new RuntimeActionResult
        {
            Ok = true,
            Status = "checking",
            Detail = "Checking Codrex runtime...",
            RepoRoot = _runtimeService.RepoRoot,
            RepoRev = "",
            ControllerPort = _runtimeService.ReadControllerConfig().Port,
            RuntimeDir = _stateStore.RuntimeDir,
            LogsDir = _stateStore.LogsDir,
        };

        var selectedNetworkUrl = BuildSelectedNetworkUrl();
        var routeHost = GetSelectedRouteHost();
        var state = new
        {
            status = runtime.Status,
            statusTone = ResolveStatusTone(runtime.Status, _actionBusy, _errorDetail),
            detail = string.IsNullOrWhiteSpace(_errorDetail) ? _statusDetailOrRuntime(runtime.Detail) : _errorDetail,
            actionBusy = _actionBusy,
            actionLabel = _actionBusy ? "Working..." : "",
            appVersion = runtime.AppVersion,
            repoRev = runtime.RepoRev,
            controllerPort = runtime.ControllerPort,
            uiMode = runtime.UiMode,
            route = _preferences.PreferredPairRoute,
            routeHost,
            lanHost = _lastNetInfo?.LanIp ?? "",
            tailscaleHost = _lastNetInfo?.TailscaleIp ?? "",
            lanAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.LanIp),
            tailscaleAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.TailscaleIp),
            sessionPresent = runtime.SessionPresent,
            localUrl = runtime.LocalUrl,
            networkUrl = selectedNetworkUrl,
            pairLink = _currentPairing?.PairLink ?? "",
            qrImageUrl = _currentPairing?.QrImageUrl ?? "",
            qrVisible = !string.IsNullOrWhiteSpace(_currentPairing?.QrImageUrl),
            pairDetail = _currentPairing?.Detail ?? "",
            pairExpiresIn = _currentPairing?.ExpiresIn ?? 0,
            logsDir = _stateStore.LogsDir,
            lastActionPath = _runtimeService.ReadLastActionPath() ?? "",
            lastErrorPath = _runtimeService.ReadLastErrorPath() ?? "",
            advancedVisible = _preferences.AdvancedVisible,
            startEnabled = !_actionBusy && !runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase) && !runtime.Status.Equals("starting", StringComparison.OrdinalIgnoreCase),
            stopEnabled = !_actionBusy && runtime.Status is not ("stopped" or "stopping"),
            showQrEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase),
            openAppEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase),
            openNetworkEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(selectedNetworkUrl),
        };

        LauncherView.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(state));

        string _statusDetailOrRuntime(string runtimeDetail) =>
            !string.IsNullOrWhiteSpace(_statusDetail) ? _statusDetail : runtimeDetail;
    }

    private string BuildSelectedNetworkUrl()
    {
        if (_lastRuntime is null || _lastRuntime.ControllerPort <= 0)
        {
            return "";
        }

        var host = GetSelectedRouteHost();
        if (string.IsNullOrWhiteSpace(host))
        {
            return "";
        }

        return $"http://{host}:{_lastRuntime.ControllerPort}/";
    }

    private string GetSelectedRouteHost()
    {
        if (NormalizeRoute(_preferences.PreferredPairRoute) == "tailscale")
        {
            return _lastNetInfo?.TailscaleIp?.Trim() ?? "";
        }

        if (!string.IsNullOrWhiteSpace(_lastNetInfo?.LanIp))
        {
            return _lastNetInfo!.LanIp.Trim();
        }

        if (_lastRuntime is { NetworkUrl.Length: > 0 })
        {
            try
            {
                return new Uri(_lastRuntime.NetworkUrl).Host;
            }
            catch
            {
            }
        }

        return "";
    }

    private static string ResolveStatusTone(string status, bool actionBusy, string errorDetail)
    {
        if (!string.IsNullOrWhiteSpace(errorDetail))
        {
            return "error";
        }

        if (actionBusy || status is "starting" or "stopping" or "checking" or "recovering")
        {
            return "busy";
        }

        return status == "running" ? "ok" : "idle";
    }

    private static string NormalizeRoute(string? raw)
    {
        var value = (raw ?? string.Empty).Trim().ToLowerInvariant();
        return value == "tailscale" ? "tailscale" : "lan";
    }

    private static void OpenUrl(string url)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true,
        });
    }

    private static void OpenDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = "explorer.exe",
            Arguments = $"\"{path}\"",
            UseShellExecute = true,
        });
    }
}
