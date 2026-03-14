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
    private static readonly TimeSpan IdleRefreshInterval = TimeSpan.FromSeconds(4);
    private static readonly TimeSpan BusyRefreshInterval = TimeSpan.FromMilliseconds(700);
    private static readonly TimeSpan NetInfoRefreshInterval = TimeSpan.FromSeconds(15);

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
    private long _lastActionEventId;
    private string _pendingAction = "";
    private string _statusDetail = "Launcher ready.";
    private string _errorDetail = "";
    private string _lastPublishedStateJson = "";
    private string _lastActionMessage = "launcher ready";
    private string _lastActionKind = "launcher";
    private string _lastActionAt = DateTime.Now.ToString("HH:mm:ss");
    private DateTime _lastNetInfoRefreshUtc = DateTime.MinValue;

    public MainWindow()
    {
        InitializeComponent();
        var repoRoot = LauncherRuntimeService.FindRepoRoot();
        _stateStore = new LauncherStateStore(repoRoot);
        _runtimeService = new LauncherRuntimeService(repoRoot, _stateStore);
        _preferences = _stateStore.LoadPreferences();
        _refreshTimer = new DispatcherTimer
        {
            Interval = IdleRefreshInterval,
        };
        _refreshTimer.Tick += async (_, _) => await RefreshStateAsync();
        Loaded += async (_, _) => await InitializeLauncherAsync();
        Closed += (_, _) => _refreshTimer.Stop();
    }

    private void UpdateRefreshInterval()
    {
        _refreshTimer.Interval = _actionBusy ? BusyRefreshInterval : IdleRefreshInterval;
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
            UpdateRefreshInterval();
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
                    RecordActionEvent("launcher", "launcher ready");
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
                        var routeHost = route == "tailscale"
                            ? (_lastNetInfo?.TailscaleIp?.Trim() ?? "")
                            : (_lastNetInfo?.LanIp?.Trim() ?? "");
                        RecordActionEvent("route", string.IsNullOrWhiteSpace(routeHost)
                            ? $"{route} selected"
                            : $"{route} selected -> {routeHost}");
                        await PublishStateAsync();
                    }
                    break;
                case "toggleAdvanced":
                    _preferences.AdvancedVisible = !_preferences.AdvancedVisible;
                    _stateStore.SavePreferences(_preferences);
                    RecordActionEvent("ui", _preferences.AdvancedVisible ? "advanced opened" : "advanced closed");
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
                        RecordActionEvent("open", $"opened local ui -> {runtime.LocalUrl}");
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
                        RecordActionEvent("open", $"opened network ui -> {networkUrl}");
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
                        RecordActionEvent("open", $"opened fallback -> {fallbackUrl}");
                        await PublishStateAsync();
                    }
                    break;
                case "copyPairLink":
                    if (!string.IsNullOrWhiteSpace(_currentPairing?.PairLink))
                    {
                        Clipboard.SetText(_currentPairing.PairLink);
                        _statusDetail = "Copied pairing link.";
                        _errorDetail = "";
                        RecordActionEvent("copy", "copied pairing link");
                        await PublishStateAsync();
                    }
                    break;
                case "copyLogPath":
                    Clipboard.SetText(_stateStore.LogsDir);
                    _statusDetail = "Copied logs path.";
                    _errorDetail = "";
                    RecordActionEvent("copy", "copied logs path");
                    await PublishStateAsync();
                    break;
                case "copyLastError":
                    if (File.Exists(_stateStore.LastErrorPath))
                    {
                        Clipboard.SetText(_stateStore.LastErrorPath);
                        _statusDetail = "Copied last error path.";
                        _errorDetail = "";
                        RecordActionEvent("copy", "copied last error path");
                        await PublishStateAsync();
                    }
                    break;
                case "openLogs":
                    OpenDirectory(_stateStore.LogsDir);
                    _statusDetail = "Opened Codrex logs.";
                    _errorDetail = "";
                    RecordActionEvent("open", "opened logs directory");
                    await PublishStateAsync();
                    break;
            }
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
            RecordActionEvent("error", $"launcher error -> {ex.Message}");
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
        RecordActionEvent(action, action == "start" ? "starting codrex runtime" : action == "stop" ? "stopping codrex runtime" : $"running {action}");
        UpdateRefreshInterval();
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
                RecordActionEvent("error", $"{action} failed -> {_errorDetail}");
            }
            else
            {
                _statusDetail = string.IsNullOrWhiteSpace(result.Detail) ? $"Codrex {action} complete." : result.Detail;
                RecordActionEvent(action, $"{action} complete");
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
            RecordActionEvent("error", $"{action} exception -> {ex.Message}");
        }
        finally
        {
            if (generation == _actionGeneration)
            {
                _actionBusy = false;
                _pendingAction = "";
                UpdateRefreshInterval();
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
                var host = GetSelectedRouteHost();
                RecordActionEvent(
                    "qr",
                    string.IsNullOrWhiteSpace(host)
                        ? $"qr generated for {_preferences.PreferredPairRoute}"
                        : $"qr generated for {_preferences.PreferredPairRoute} -> {host}");
            }
            else
            {
                _errorDetail = _currentPairing.Detail;
                RecordActionEvent("error", $"qr failed -> {_errorDetail}");
            }
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
            RecordActionEvent("error", $"qr exception -> {ex.Message}");
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
                var shouldRefreshNetInfo =
                    _actionBusy ||
                    _lastNetInfo is null ||
                    DateTime.UtcNow - _lastNetInfoRefreshUtc >= NetInfoRefreshInterval;
                if (shouldRefreshNetInfo)
                {
                    var config = _runtimeService.ReadControllerConfig();
                    _lastNetInfo = await _runtimeService.GetNetInfoAsync(_lastRuntime.ControllerPort, config.Token);
                    _lastNetInfoRefreshUtc = DateTime.UtcNow;
                }
            }
            else
            {
                _lastNetInfo = null;
                _lastNetInfoRefreshUtc = DateTime.MinValue;
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
            UpdateRefreshInterval();
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
            UpdateRefreshInterval();
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
            actionLabel = _actionBusy ? (_pendingAction == "showQr" ? "QR..." : "Working...") : "",
            appVersion = runtime.AppVersion,
            repoRev = runtime.RepoRev,
            controllerPort = runtime.ControllerPort,
            route = _preferences.PreferredPairRoute,
            routeHost,
            lanHost = _lastNetInfo?.LanIp ?? "",
            tailscaleHost = _lastNetInfo?.TailscaleIp ?? "",
            lanAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.LanIp),
            tailscaleAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.TailscaleIp),
            pairLink = _currentPairing?.PairLink ?? "",
            qrImageUrl = _currentPairing?.QrImageUrl ?? "",
            qrVisible = !string.IsNullOrWhiteSpace(_currentPairing?.QrImageUrl),
            pairDetail = _currentPairing?.Detail ?? "",
            logsDir = _stateStore.LogsDir,
            advancedVisible = _preferences.AdvancedVisible,
            startEnabled = !_actionBusy && !runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase) && !runtime.Status.Equals("starting", StringComparison.OrdinalIgnoreCase),
            stopEnabled = !_actionBusy && runtime.Status is not ("stopped" or "stopping"),
            showQrEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase),
            openAppEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase),
            openNetworkEnabled = !_actionBusy && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(selectedNetworkUrl),
            actionEventId = _lastActionEventId,
            actionEventMessage = _lastActionMessage,
            actionEventKind = _lastActionKind,
            actionEventAt = _lastActionAt,
        };

        var stateJson = JsonSerializer.Serialize(state);
        if (string.Equals(stateJson, _lastPublishedStateJson, StringComparison.Ordinal))
        {
            return;
        }

        _lastPublishedStateJson = stateJson;
        LauncherView.CoreWebView2.PostWebMessageAsJson(stateJson);

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

    private void RecordActionEvent(string kind, string message)
    {
        _lastActionEventId += 1;
        _lastActionKind = string.IsNullOrWhiteSpace(kind) ? "launcher" : kind.Trim().ToLowerInvariant();
        _lastActionMessage = string.IsNullOrWhiteSpace(message) ? "ok" : message.Trim();
        _lastActionAt = DateTime.Now.ToString("HH:mm:ss");
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
