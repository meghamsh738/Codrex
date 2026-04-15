using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.Json;
using System.ComponentModel;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;
using Forms = System.Windows.Forms;
using Drawing = System.Drawing;

namespace Codrex.Launcher;

public partial class MainWindow : Window
{
    private static readonly TimeSpan IdleRefreshInterval = TimeSpan.FromSeconds(4);
    private static readonly TimeSpan BusyRefreshInterval = TimeSpan.FromMilliseconds(700);
    private static readonly TimeSpan NetInfoRefreshInterval = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan AccountsRefreshInterval = TimeSpan.FromMinutes(5);

    private readonly LauncherRuntimeService _runtimeService;
    private readonly LauncherStateStore _stateStore;
    private readonly DispatcherTimer _refreshTimer;
    private readonly LauncherPreferences _preferences;
    private RuntimeActionResult? _lastRuntime;
    private PairingResult? _currentPairing;
    private NetInfoPayload? _lastNetInfo;
    private LauncherAccountsPayload? _lastAccounts;
    private LauncherPrivacyLockStatus? _lastPrivacyLock;
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
    private DateTime _lastAccountsRefreshUtc = DateTime.MinValue;
    private bool _refreshInFlight;
    private bool _refreshQueued;
    private string _routeNotice = "";
    private readonly Forms.NotifyIcon _trayIcon;
    private readonly Forms.ContextMenuStrip _trayMenu;
    private readonly Forms.ToolStripMenuItem _trayShowItem;
    private readonly Forms.ToolStripMenuItem _trayStartItem;
    private readonly Forms.ToolStripMenuItem _trayStopItem;
    private readonly Forms.ToolStripMenuItem _trayPairItem;
    private readonly Forms.ToolStripMenuItem _trayOpenLocalItem;
    private readonly Forms.ToolStripMenuItem _trayOpenNetworkItem;
    private readonly Forms.ToolStripMenuItem _trayToggleStartupItem;
    private readonly Forms.ToolStripMenuItem _trayExitItem;
    private readonly bool _startHiddenToTray;
    private readonly string _startupBootstrapLogPath;
    private bool _startupEnabled;
    private bool _startupBusy;
    private bool _allowClose;
    private bool _trayInitialized;

    public MainWindow(bool startHiddenToTray = false)
    {
        InitializeComponent();
        var repoRoot = LauncherRuntimeService.FindRepoRoot();
        _stateStore = new LauncherStateStore(repoRoot);
        _runtimeService = new LauncherRuntimeService(repoRoot, _stateStore);
        _preferences = _stateStore.LoadPreferences();
        _startHiddenToTray = startHiddenToTray;
        Directory.CreateDirectory(_stateStore.LogsDir);
        _startupBootstrapLogPath = Path.Combine(_stateStore.LogsDir, "startup-bootstrap.log");
        WriteStartupBreadcrumb($"constructed startHiddenToTray={_startHiddenToTray}");
        _refreshTimer = new DispatcherTimer
        {
            Interval = IdleRefreshInterval,
        };
        _trayMenu = new Forms.ContextMenuStrip();
        _trayShowItem = new Forms.ToolStripMenuItem("Show Launcher", null, (_, _) => RestoreFromTray());
        _trayStartItem = new Forms.ToolStripMenuItem("Start Codrex", null, async (_, _) => await RunRuntimeActionAsync("start"));
        _trayStopItem = new Forms.ToolStripMenuItem("Stop Codrex", null, async (_, _) => await RunRuntimeActionAsync("stop"));
        _trayPairItem = new Forms.ToolStripMenuItem("Show Pair QR", null, async (_, _) =>
        {
            RestoreFromTray();
            await GeneratePairingAsync();
        });
        _trayOpenLocalItem = new Forms.ToolStripMenuItem("Open Local App", null, (_, _) =>
        {
            RestoreFromTray();
            if (_lastRuntime is { Ok: true } runtime && !string.IsNullOrWhiteSpace(runtime.LocalUrl))
            {
                OpenUrl(runtime.LocalUrl);
            }
        });
        _trayOpenNetworkItem = new Forms.ToolStripMenuItem("Open Network App", null, (_, _) =>
        {
            RestoreFromTray();
            var networkUrl = BuildSelectedNetworkUrl();
            if (!string.IsNullOrWhiteSpace(networkUrl))
            {
                OpenUrl(networkUrl);
            }
        });
        _trayToggleStartupItem = new Forms.ToolStripMenuItem("Enable Startup", null, async (_, _) => await ToggleStartupAsync());
        _trayExitItem = new Forms.ToolStripMenuItem("Exit Launcher", null, (_, _) => ExitLauncher());
        _trayMenu.Items.AddRange(new Forms.ToolStripItem[]
        {
            _trayShowItem,
            new Forms.ToolStripSeparator(),
            _trayStartItem,
            _trayStopItem,
            _trayPairItem,
            _trayOpenLocalItem,
            _trayOpenNetworkItem,
            new Forms.ToolStripSeparator(),
            _trayToggleStartupItem,
            new Forms.ToolStripSeparator(),
            _trayExitItem,
        });
        _trayIcon = new Forms.NotifyIcon
        {
            Icon = Drawing.Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location) ?? Drawing.SystemIcons.Application,
            Visible = false,
            Text = "Codrex Launcher",
            ContextMenuStrip = _trayMenu,
        };
        _trayIcon.DoubleClick += (_, _) => RestoreFromTray();
        _refreshTimer.Tick += async (_, _) => await RefreshStateAsync();
        Loaded += async (_, _) => await InitializeLauncherAsync();
        StateChanged += (_, _) =>
        {
            if (WindowState == WindowState.Minimized && _preferences.MinimizeToTray)
            {
                HideToTray("Launcher is still running in the tray.");
            }
        };
        Closing += OnWindowClosing;
        Closed += (_, _) =>
        {
            _refreshTimer.Stop();
            _trayIcon.Visible = false;
            _trayIcon.Dispose();
            _trayMenu.Dispose();
        };
    }

    private void UpdateRefreshInterval()
    {
        _refreshTimer.Interval = _actionBusy ? BusyRefreshInterval : IdleRefreshInterval;
    }

    private async Task InitializeLauncherAsync()
    {
        try
        {
            WriteStartupBreadcrumb("initializing launcher UI");
            var webViewUserDataDir = Path.Combine(_stateStore.RuntimeDir, "launcher-webview");
            Directory.CreateDirectory(webViewUserDataDir);
            var webViewEnvironment = await CoreWebView2Environment.CreateAsync(userDataFolder: webViewUserDataDir);
            await LauncherView.EnsureCoreWebView2Async(webViewEnvironment);
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
            _trayInitialized = true;
            _trayIcon.Visible = true;
            WriteStartupBreadcrumb("tray icon visible");
            await RefreshStartupStateAsync();
            UpdateTrayState();
            if (_startHiddenToTray)
            {
                WriteStartupBreadcrumb("startup requested hidden to tray");
                Dispatcher.BeginInvoke(() => HideToTray("Launcher started in the tray."), DispatcherPriority.ApplicationIdle);
            }
            await RefreshStateAsync();
        }
        catch (Exception ex)
        {
            WriteStartupBreadcrumb($"initialize failed: {ex.Message}");
            System.Windows.MessageBox.Show(
                $"Codrex desktop launcher could not initialize WebView2.\n\n{ex.Message}",
                "Codrex Launcher",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            _allowClose = true;
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
                        _routeNotice = "";
                        _statusDetail = $"Selected {route} route.";
                        var routeHost = GetRouteHost(route);
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
                case "toggleStartup":
                    await ToggleStartupAsync();
                    break;
                case "privacySetPin":
                    if (root.TryGetProperty("newPin", out var newPinProperty))
                    {
                        await SavePrivacyPinAsync(newPinProperty.GetString() ?? string.Empty, string.Empty);
                    }
                    break;
                case "privacyChangePin":
                    await SavePrivacyPinAsync(
                        root.TryGetProperty("newPin", out var changedPinProperty) ? changedPinProperty.GetString() ?? string.Empty : string.Empty,
                        root.TryGetProperty("currentPin", out var currentPinProperty) ? currentPinProperty.GetString() ?? string.Empty : string.Empty);
                    break;
                case "privacyClearPin":
                    await ClearPrivacyPinAsync(root.TryGetProperty("currentPin", out var clearCurrentPinProperty) ? clearCurrentPinProperty.GetString() ?? string.Empty : string.Empty);
                    break;
                case "toggleMinimizeToTray":
                    _preferences.MinimizeToTray = !_preferences.MinimizeToTray;
                    _stateStore.SavePreferences(_preferences);
                    _statusDetail = _preferences.MinimizeToTray
                        ? "Launcher will hide to tray when minimized or closed."
                        : "Launcher will close normally when you exit.";
                    _errorDetail = "";
                    RecordActionEvent("tray", _preferences.MinimizeToTray ? "minimize to tray enabled" : "minimize to tray disabled");
                    UpdateTrayState();
                    await PublishStateAsync();
                    break;
                case "hideToTray":
                    HideToTray("Launcher hidden to tray.");
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
                        System.Windows.Clipboard.SetText(_currentPairing.PairLink);
                        _statusDetail = "Copied pairing link.";
                        _errorDetail = "";
                        RecordActionEvent("copy", "copied pairing link");
                        await PublishStateAsync();
                    }
                    break;
                case "copyLogPath":
                    System.Windows.Clipboard.SetText(_stateStore.LogsDir);
                    _statusDetail = "Copied logs path.";
                    _errorDetail = "";
                    RecordActionEvent("copy", "copied logs path");
                    await PublishStateAsync();
                    break;
                case "activateAccount":
                    if (root.TryGetProperty("accountId", out var accountProperty))
                    {
                        var accountId = (accountProperty.GetString() ?? string.Empty).Trim();
                        if (!string.IsNullOrWhiteSpace(accountId))
                        {
                            var activated = await _runtimeService.ActivateAccountAsync(accountId);
                            _lastAccountsRefreshUtc = DateTime.MinValue;
                            _lastAccounts = await _runtimeService.GetAccountsAsync(forceUsage: true);
                            _statusDetail = $"Active account is now {activated?.Label ?? accountId}.";
                            _errorDetail = "";
                            RecordActionEvent("account", $"active account -> {activated?.Label ?? accountId}");
                            await PublishStateAsync();
                        }
                    }
                    break;
                case "openAccountSelector":
                    OpenScript("open-codex-wsl-selector.ps1");
                    _statusDetail = "Opened account selector.";
                    _errorDetail = "";
                    RecordActionEvent("open", "opened account selector");
                    await PublishStateAsync();
                    break;
                case "openSessionSwitcher":
                    OpenScript("open-codex-session-switcher.ps1");
                    _statusDetail = "Opened session switcher.";
                    _errorDetail = "";
                    RecordActionEvent("open", "opened session switcher");
                    await PublishStateAsync();
                    break;
                case "openUbuntuCodex":
                    OpenScript("open-ubuntu-codex.ps1");
                    _statusDetail = "Opened Ubuntu Codex.";
                    _errorDetail = "";
                    RecordActionEvent("open", "opened ubuntu codex");
                    await PublishStateAsync();
                    break;
                case "copyLastError":
                    if (File.Exists(_stateStore.LastErrorPath))
                    {
                        System.Windows.Clipboard.SetText(_stateStore.LastErrorPath);
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
        _routeNotice = "";
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

    private async Task SavePrivacyPinAsync(string newPin, string currentPin)
    {
        if (_lastRuntime is null || !_lastRuntime.Ok || !_lastRuntime.Status.Equals("running", StringComparison.OrdinalIgnoreCase))
        {
            _errorDetail = "Start Codrex before managing the privacy PIN.";
            await PublishStateAsync();
            return;
        }

        var config = _runtimeService.ReadControllerConfig();
        _lastPrivacyLock = await _runtimeService.SavePrivacyPinAsync(_lastRuntime.ControllerPort, config.Token, newPin, currentPin);
        _statusDetail = "Privacy PIN saved.";
        _errorDetail = "";
        RecordActionEvent("privacy", "privacy pin saved");
        await PublishStateAsync();
    }

    private async Task ClearPrivacyPinAsync(string currentPin)
    {
        if (_lastRuntime is null || !_lastRuntime.Ok || !_lastRuntime.Status.Equals("running", StringComparison.OrdinalIgnoreCase))
        {
            _errorDetail = "Start Codrex before managing the privacy PIN.";
            await PublishStateAsync();
            return;
        }

        var config = _runtimeService.ReadControllerConfig();
        _lastPrivacyLock = await _runtimeService.ClearPrivacyPinAsync(_lastRuntime.ControllerPort, config.Token, currentPin);
        _statusDetail = "Privacy PIN cleared.";
        _errorDetail = "";
        RecordActionEvent("privacy", "privacy pin cleared");
        await PublishStateAsync();
    }

    private async Task RefreshStateAsync()
    {
        if (_refreshInFlight)
        {
            _refreshQueued = true;
            return;
        }

        _refreshInFlight = true;
        try
        {
            do
            {
                _refreshQueued = false;

                try
                {
                    _lastRuntime = await _runtimeService.GetStatusAsync();
                    TryCompletePendingActionFromLiveState(_lastRuntime);
                    _errorDetail = "";
                }
                catch (Exception ex)
                {
                    _errorDetail = ex.Message;
                    _routeNotice = "";
                    await PublishStateAsync();
                    return;
                }

                if (_lastRuntime.Ok && _lastRuntime.Status.Equals("running", StringComparison.OrdinalIgnoreCase))
                {
                    var shouldRefreshNetInfo =
                        _actionBusy ||
                        _lastNetInfo is null ||
                        DateTime.UtcNow - _lastNetInfoRefreshUtc >= NetInfoRefreshInterval;
                    if (shouldRefreshNetInfo)
                    {
                        try
                        {
                            var config = _runtimeService.ReadControllerConfig();
                            _lastNetInfo = await _runtimeService.GetNetInfoAsync(_lastRuntime.ControllerPort, config.Token);
                            _lastNetInfoRefreshUtc = DateTime.UtcNow;
                            _routeNotice = "";
                        }
                        catch (Exception ex)
                        {
                            _routeNotice = string.IsNullOrWhiteSpace(_lastNetInfo?.LanIp)
                                && string.IsNullOrWhiteSpace(_lastNetInfo?.TailscaleIp)
                                && string.IsNullOrWhiteSpace(_lastNetInfo?.NetbirdIp)
                                ? "Route lookup is delayed right now."
                                : "Using the last known route while lookup catches up.";
                            RecordActionEvent("network", $"route refresh delayed -> {ex.Message}");
                        }
                    }

                    try
                    {
                        var config = _runtimeService.ReadControllerConfig();
                        _lastPrivacyLock = await _runtimeService.GetPrivacyLockStatusAsync(_lastRuntime.ControllerPort, config.Token);
                    }
                    catch (Exception ex)
                    {
                        if (_lastPrivacyLock is null)
                        {
                            RecordActionEvent("privacy", $"privacy status unavailable -> {ex.Message}");
                        }
                    }
                }
                else
                {
                    _lastNetInfo = null;
                    _lastPrivacyLock = null;
                    _lastNetInfoRefreshUtc = DateTime.MinValue;
                    _routeNotice = "";
                }

                var shouldRefreshAccounts =
                    _lastAccounts is null ||
                    DateTime.UtcNow - _lastAccountsRefreshUtc >= AccountsRefreshInterval;
                if (shouldRefreshAccounts)
                {
                    try
                    {
                        var forceUsage = _lastAccounts is null;
                        _lastAccounts = await _runtimeService.GetAccountsAsync(forceUsage);
                        _lastAccountsRefreshUtc = DateTime.UtcNow;
                    }
                    catch (Exception ex)
                    {
                        RecordActionEvent("accounts", $"account refresh delayed -> {ex.Message}");
                    }
                }

                await PublishStateAsync();
            }
            while (_refreshQueued);
        }
        finally
        {
            _refreshInFlight = false;
        }
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

    private Task PublishStateAsync()
    {
        if (!_webReady || LauncherView.CoreWebView2 is null)
        {
            return Task.CompletedTask;
        }

        UpdateTrayState();

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
            currentAccountId = _lastAccounts?.ActiveAccountId ?? "",
            realCodexPath = _lastAccounts?.RealCodexPath ?? "",
            accounts = (_lastAccounts?.Accounts ?? new List<LauncherAccountSummary>()).Select(account => new
            {
                id = account.Id,
                label = account.Label,
                codexHome = account.CodexHome,
                active = account.Active,
                implicitPrimary = account.ImplicitPrimary,
                planType = account.AuthProfile?.PlanType ?? "",
                subscriptionActiveUntil = account.AuthProfile?.SubscriptionActiveUntil ?? "",
                usageContextLeft = account.Usage?.ContextLeft ?? "",
                usageWeeklyLeft = account.Usage?.WeeklyLeft ?? "",
                usageTip = account.Usage?.Tip ?? "",
                usageStale = account.Usage?.Stale ?? false,
                usageDetail = account.Usage?.Detail ?? "",
            }),
            route = _preferences.PreferredPairRoute,
            routeHost,
            routeNote = _routeNotice,
            routeProvider = _lastNetInfo?.RouteProvider ?? "",
            routeState = _lastNetInfo?.RouteState ?? "",
            preferredOrigin = _lastNetInfo?.PreferredOrigin ?? "",
            lanHost = _lastNetInfo?.LanIp ?? "",
            tailscaleHost = _lastNetInfo?.TailscaleIp ?? "",
            netbirdHost = _lastNetInfo?.NetbirdIp ?? "",
            lanAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.LanIp),
            tailscaleAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.TailscaleIp),
            netbirdAvailable = !string.IsNullOrWhiteSpace(_lastNetInfo?.NetbirdIp),
            controllerMode = runtime.ControllerMode,
            sessionsRuntimeState = runtime.SessionsRuntimeState,
            pairLink = _currentPairing?.PairLink ?? "",
            qrImageUrl = _currentPairing?.QrImageUrl ?? "",
            qrVisible = !string.IsNullOrWhiteSpace(_currentPairing?.QrImageUrl),
            pairDetail = _currentPairing?.Detail ?? "",
            privacySupported = _lastPrivacyLock?.Supported ?? false,
            privacyPinConfigured = _lastPrivacyLock?.PinConfigured ?? false,
            privacyActive = _lastPrivacyLock?.Active ?? false,
            privacyDetail = _lastPrivacyLock?.Detail ?? "",
            privacyOwner = _lastPrivacyLock?.OwnerDeviceName ?? "",
            privacyHelperReady = _lastPrivacyLock?.HelperReady ?? false,
            privacyHelperError = _lastPrivacyLock?.HelperError ?? "",
            logsDir = _stateStore.LogsDir,
            advancedVisible = _preferences.AdvancedVisible,
            minimizeToTray = _preferences.MinimizeToTray,
            startupEnabled = _startupEnabled,
            startupBusy = _startupBusy,
            trayReady = _trayInitialized,
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
            return Task.CompletedTask;
        }

        _lastPublishedStateJson = stateJson;
        LauncherView.CoreWebView2.PostWebMessageAsJson(stateJson);

        string _statusDetailOrRuntime(string runtimeDetail) =>
            !string.IsNullOrWhiteSpace(_statusDetail) ? _statusDetail : runtimeDetail;
        return Task.CompletedTask;
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
        return GetRouteHost(_preferences.PreferredPairRoute);
    }

    private string GetRouteHost(string? route)
    {
        var normalized = NormalizeRoute(route);
        if (normalized == "preferred")
        {
            if (!string.IsNullOrWhiteSpace(_lastNetInfo?.PreferredOrigin))
            {
                try
                {
                    return new Uri(_lastNetInfo.PreferredOrigin).Host;
                }
                catch
                {
                }
            }
        }

        if (normalized == "tailscale")
        {
            return _lastNetInfo?.TailscaleIp?.Trim() ?? "";
        }

        if (normalized == "netbird")
        {
            return _lastNetInfo?.NetbirdIp?.Trim() ?? "";
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
        return value switch
        {
            "tailscale" => "tailscale",
            "netbird" => "netbird",
            "lan" => "lan",
            "current" => "current",
            _ => "preferred",
        };
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

    private void OpenScript(string scriptName)
    {
        var scriptPath = Path.Combine(_runtimeService.RepoRoot, "tools", "windows", scriptName);
        if (!File.Exists(scriptPath))
        {
            throw new FileNotFoundException($"Launcher helper is missing: {scriptName}", scriptPath);
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{scriptPath}\"",
            WorkingDirectory = _runtimeService.RepoRoot,
            UseShellExecute = true,
        });
    }

    private async Task ToggleStartupAsync()
    {
        if (_startupBusy)
        {
            return;
        }

        _startupBusy = true;
        UpdateTrayState();
        await PublishStateAsync();
        try
        {
            await _runtimeService.SetStartupEnabledAsync(!_startupEnabled);
            _startupEnabled = !_startupEnabled;
            _statusDetail = _startupEnabled
                ? "Autostart and watchdog are enabled."
                : "Autostart and watchdog are disabled.";
            _errorDetail = "";
            RecordActionEvent("startup", _startupEnabled ? "startup enabled" : "startup disabled");
        }
        catch (Exception ex)
        {
            _errorDetail = ex.Message;
            RecordActionEvent("error", $"startup toggle failed -> {ex.Message}");
        }
        finally
        {
            _startupBusy = false;
            UpdateTrayState();
            await PublishStateAsync();
        }
    }

    private async Task RefreshStartupStateAsync()
    {
        try
        {
            _startupEnabled = await _runtimeService.GetStartupEnabledAsync();
        }
        catch (Exception ex)
        {
            RecordActionEvent("startup", $"startup status unavailable -> {ex.Message}");
        }
    }

    private void UpdateTrayState()
    {
        var runtimeRunning = _lastRuntime is { Ok: true } runtime && runtime.Status.Equals("running", StringComparison.OrdinalIgnoreCase);
        _trayIcon.Text = runtimeRunning ? "Codrex Launcher: running" : "Codrex Launcher: stopped";
        _trayShowItem.Text = IsVisible ? "Focus Launcher" : "Show Launcher";
        _trayStartItem.Enabled = !_actionBusy && !runtimeRunning;
        _trayStopItem.Enabled = !_actionBusy && runtimeRunning;
        _trayPairItem.Enabled = !_actionBusy && runtimeRunning;
        _trayOpenLocalItem.Enabled = !_actionBusy && runtimeRunning && !string.IsNullOrWhiteSpace(_lastRuntime?.LocalUrl);
        _trayOpenNetworkItem.Enabled = !_actionBusy && runtimeRunning && !string.IsNullOrWhiteSpace(BuildSelectedNetworkUrl());
        _trayToggleStartupItem.Text = _startupBusy
            ? "Updating Startup..."
            : _startupEnabled ? "Disable Startup" : "Enable Startup";
        _trayToggleStartupItem.Enabled = !_startupBusy;
    }

    private void HideToTray(string statusMessage)
    {
        if (!_trayInitialized)
        {
            return;
        }

        _statusDetail = statusMessage;
        _errorDetail = "";
        Opacity = 0;
        Hide();
        ShowInTaskbar = false;
        UpdateTrayState();
        WriteStartupBreadcrumb($"hidden to tray: {statusMessage}");
        _trayIcon.BalloonTipTitle = "Codrex Launcher";
        _trayIcon.BalloonTipText = statusMessage;
        try
        {
            _trayIcon.ShowBalloonTip(1800);
        }
        catch
        {
        }
    }

    private void RestoreFromTray()
    {
        Opacity = 1;
        ShowInTaskbar = true;
        if (!IsVisible)
        {
            Show();
        }
        if (WindowState == WindowState.Minimized)
        {
            WindowState = WindowState.Normal;
        }
        Activate();
        Focus();
        UpdateTrayState();
        WriteStartupBreadcrumb("restored from tray");
    }

    private void ExitLauncher()
    {
        _allowClose = true;
        Close();
    }

    private void OnWindowClosing(object? sender, CancelEventArgs e)
    {
        if (_allowClose)
        {
            return;
        }

        if (_preferences.MinimizeToTray)
        {
            e.Cancel = true;
            HideToTray("Launcher hidden to tray. Use the tray icon to restore it.");
        }
    }

    private void WriteStartupBreadcrumb(string message)
    {
        try
        {
            var stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            File.AppendAllText(_startupBootstrapLogPath, $"{stamp} [launcher] {message}{Environment.NewLine}");
        }
        catch
        {
        }
    }
}
