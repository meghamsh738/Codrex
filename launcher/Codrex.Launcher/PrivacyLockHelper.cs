using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using Forms = System.Windows.Forms;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;
using WpfApplication = System.Windows.Application;
using WpfHorizontalAlignment = System.Windows.HorizontalAlignment;

namespace Codrex.Launcher;

internal sealed class PrivacyLockHelperOptions
{
    public string RuntimeDir { get; init; } = "";
    public string StateFile { get; init; } = "";
    public string ConfigFile { get; init; } = "";
    public string LockId { get; init; } = "";
    public string CallbackToken { get; init; } = "";
    public int ControllerPort { get; init; }

    public static bool TryParse(string[] args, out PrivacyLockHelperOptions? options)
    {
        options = null;
        if (args is null || !args.Any(arg => string.Equals(arg, "--privacy-lock-helper", StringComparison.OrdinalIgnoreCase)))
        {
            return false;
        }

        string runtimeDir = "";
        string stateFile = "";
        string configFile = "";
        string lockId = "";
        string callbackToken = "";
        int controllerPort = 0;

        for (var i = 0; i < args.Length; i += 1)
        {
            var key = args[i] ?? string.Empty;
            if (!key.StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }

            string value = "";
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                value = args[i + 1] ?? string.Empty;
                i += 1;
            }

            switch (key.Trim().ToLowerInvariant())
            {
                case "--runtime-dir":
                    runtimeDir = value.Trim();
                    break;
                case "--state-file":
                    stateFile = value.Trim();
                    break;
                case "--config-file":
                    configFile = value.Trim();
                    break;
                case "--lock-id":
                    lockId = value.Trim();
                    break;
                case "--callback-token":
                    callbackToken = value.Trim();
                    break;
                case "--controller-port":
                    int.TryParse(value, out controllerPort);
                    break;
            }
        }

        if (string.IsNullOrWhiteSpace(stateFile) || string.IsNullOrWhiteSpace(configFile) || string.IsNullOrWhiteSpace(lockId))
        {
            return false;
        }

        options = new PrivacyLockHelperOptions
        {
            RuntimeDir = runtimeDir,
            StateFile = Path.GetFullPath(stateFile),
            ConfigFile = Path.GetFullPath(configFile),
            LockId = lockId,
            CallbackToken = callbackToken,
            ControllerPort = controllerPort,
        };
        return true;
    }
}

internal sealed class PrivacyLockConfigPayload
{
    [JsonPropertyName("pin_configured")]
    public bool PinConfigured { get; set; }

    [JsonPropertyName("pin_salt_b64")]
    public string PinSaltBase64 { get; set; } = "";

    [JsonPropertyName("pin_hash_b64")]
    public string PinHashBase64 { get; set; } = "";

    [JsonPropertyName("pin_iterations")]
    public int PinIterations { get; set; } = 200000;
}

internal sealed class PrivacyLockStatePayload
{
    [JsonPropertyName("active")]
    public bool Active { get; set; }

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "hard";

    [JsonPropertyName("display_scope")]
    public string DisplayScope { get; set; } = "all";

    [JsonPropertyName("owner_device_id")]
    public string OwnerDeviceId { get; set; } = "";

    [JsonPropertyName("owner_device_name")]
    public string OwnerDeviceName { get; set; } = "";

    [JsonPropertyName("locked_at")]
    public double LockedAt { get; set; }

    [JsonPropertyName("updated_at")]
    public double UpdatedAt { get; set; }

    [JsonPropertyName("lock_id")]
    public string LockId { get; set; } = "";

    [JsonPropertyName("callback_token")]
    public string CallbackToken { get; set; } = "";

    [JsonPropertyName("controller_port")]
    public int ControllerPort { get; set; }

    [JsonPropertyName("helper_pid")]
    public int HelperPid { get; set; }

    [JsonPropertyName("helper_ready")]
    public bool HelperReady { get; set; }

    [JsonPropertyName("helper_error")]
    public string HelperError { get; set; } = "";

    [JsonPropertyName("last_unlock_source")]
    public string LastUnlockSource { get; set; } = "";
}

internal sealed class PrivacyLockFileStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = null,
        WriteIndented = true,
    };

    public PrivacyLockFileStore(string configFile, string stateFile)
    {
        ConfigFile = configFile;
        StateFile = stateFile;
    }

    public string ConfigFile { get; }
    public string StateFile { get; }

    public PrivacyLockConfigPayload LoadConfig()
    {
        try
        {
            if (!File.Exists(ConfigFile))
            {
                return new PrivacyLockConfigPayload();
            }

            var raw = File.ReadAllText(ConfigFile);
            return JsonSerializer.Deserialize<PrivacyLockConfigPayload>(raw, JsonOptions) ?? new PrivacyLockConfigPayload();
        }
        catch
        {
            return new PrivacyLockConfigPayload();
        }
    }

    public PrivacyLockStatePayload LoadState()
    {
        try
        {
            if (!File.Exists(StateFile))
            {
                return new PrivacyLockStatePayload();
            }

            var raw = File.ReadAllText(StateFile);
            return JsonSerializer.Deserialize<PrivacyLockStatePayload>(raw, JsonOptions) ?? new PrivacyLockStatePayload();
        }
        catch
        {
            return new PrivacyLockStatePayload();
        }
    }

    public void SaveState(PrivacyLockStatePayload state)
    {
        var directory = Path.GetDirectoryName(StateFile);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var temp = $"{StateFile}.tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions));
        File.Move(temp, StateFile, overwrite: true);
    }

    public bool VerifyPin(string pin)
    {
        var config = LoadConfig();
        if (!config.PinConfigured || string.IsNullOrWhiteSpace(config.PinSaltBase64) || string.IsNullOrWhiteSpace(config.PinHashBase64))
        {
            return false;
        }

        try
        {
            var salt = Convert.FromBase64String(config.PinSaltBase64);
            var expected = Convert.FromBase64String(config.PinHashBase64);
            var actual = Rfc2898DeriveBytes.Pbkdf2(
                pin.Trim(),
                salt,
                Math.Max(config.PinIterations, 1000),
                HashAlgorithmName.SHA256,
                expected.Length);
            return CryptographicOperations.FixedTimeEquals(actual, expected);
        }
        catch
        {
            return false;
        }
    }
}

internal sealed class PrivacyLockOverlayWindow : Window
{
    private readonly TextBlock _pinBlock;
    private readonly TextBlock _detailBlock;

    public PrivacyLockOverlayWindow(Forms.Screen screen)
    {
        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize;
        AllowsTransparency = false;
        ShowInTaskbar = false;
        Topmost = true;
        Left = screen.Bounds.Left;
        Top = screen.Bounds.Top;
        Width = Math.Max(1, screen.Bounds.Width);
        Height = Math.Max(1, screen.Bounds.Height);
        Background = new SolidColorBrush(MediaColor.FromRgb(0, 0, 0));
        Title = "Codrex Privacy Lock";
        Content = BuildContent();

        _pinBlock = (TextBlock)((StackPanel)((Border)((Grid)Content).Children[0]).Child).Children[2];
        _detailBlock = (TextBlock)((StackPanel)((Border)((Grid)Content).Children[0]).Child).Children[1];
    }

    public void UpdateStatus(string detailText, string pinText)
    {
        _detailBlock.Text = detailText;
        _pinBlock.Text = pinText;
    }

    private UIElement BuildContent()
    {
        var headline = new TextBlock
        {
            Text = "Remote session active",
            Foreground = MediaBrushes.White,
            FontSize = 34,
            FontWeight = FontWeights.SemiBold,
            TextAlignment = TextAlignment.Center,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
        };

        var detail = new TextBlock
        {
            Text = "Please do not interrupt. Enter PIN to unlock locally.",
            Foreground = new SolidColorBrush(MediaColor.FromRgb(196, 206, 219)),
            FontSize = 18,
            Margin = new Thickness(0, 14, 0, 0),
            TextAlignment = TextAlignment.Center,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
        };

        var pin = new TextBlock
        {
            Text = "PIN: ",
            Foreground = MediaBrushes.White,
            FontSize = 24,
            Margin = new Thickness(0, 26, 0, 0),
            TextAlignment = TextAlignment.Center,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
            FontWeight = FontWeights.Medium,
        };

        var note = new TextBlock
        {
            Text = "Only your locking tablet can unlock remotely.",
            Foreground = new SolidColorBrush(MediaColor.FromRgb(128, 139, 154)),
            FontSize = 14,
            Margin = new Thickness(0, 16, 0, 0),
            TextAlignment = TextAlignment.Center,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
        };

        var stack = new StackPanel
        {
            Width = 720,
            MaxWidth = 720,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        };
        stack.Children.Add(headline);
        stack.Children.Add(detail);
        stack.Children.Add(pin);
        stack.Children.Add(note);

        var border = new Border
        {
            BorderBrush = new SolidColorBrush(MediaColor.FromRgb(38, 42, 50)),
            BorderThickness = new Thickness(1),
            Background = new SolidColorBrush(MediaColor.FromRgb(10, 10, 10)),
            CornerRadius = new CornerRadius(28),
            Padding = new Thickness(42, 38, 42, 38),
            Child = stack,
            HorizontalAlignment = WpfHorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        };

        var root = new Grid();
        root.Children.Add(border);
        return root;
    }
}

internal sealed class PrivacyLockHelperSession
{
    private const int WH_KEYBOARD_LL = 13;
    private const int WH_MOUSE_LL = 14;
    private const int WM_KEYDOWN = 0x0100;
    private const int WM_KEYUP = 0x0101;
    private const int WM_SYSKEYDOWN = 0x0104;
    private const int WM_SYSKEYUP = 0x0105;
    private const int VK_BACK = 0x08;
    private const int VK_RETURN = 0x0D;
    private const int VK_ESCAPE = 0x1B;
    private const int VK_NUMPAD0 = 0x60;
    private const int VK_NUMPAD9 = 0x69;
    private const uint LLKHF_INJECTED = 0x10;
    private const uint LLKHF_LOWER_IL_INJECTED = 0x02;
    private const uint LLMHF_INJECTED = 0x00000001;
    private const uint WDA_EXCLUDEFROMCAPTURE = 0x00000011;

    private readonly PrivacyLockHelperOptions _options;
    private readonly PrivacyLockFileStore _store;
    private readonly DispatcherTimer _statePollTimer;
    private readonly StringBuilder _pinBuffer = new();
    private readonly List<PrivacyLockOverlayWindow> _windows = new();
    private readonly LowLevelKeyboardProc _keyboardProc;
    private readonly LowLevelMouseProc _mouseProc;

    private IntPtr _keyboardHook = IntPtr.Zero;
    private IntPtr _mouseHook = IntPtr.Zero;
    private bool _shuttingDown;
    private string _detailText = "Please do not interrupt. Enter PIN to unlock locally.";

    public PrivacyLockHelperSession(PrivacyLockHelperOptions options)
    {
        _options = options;
        _store = new PrivacyLockFileStore(options.ConfigFile, options.StateFile);
        _keyboardProc = KeyboardHookCallback;
        _mouseProc = MouseHookCallback;
        _statePollTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(320),
        };
        _statePollTimer.Tick += (_, _) => CheckRemoteUnlockState();
    }

    public void Start()
    {
        Dispatcher.CurrentDispatcher.BeginInvoke(new Action(Initialize), DispatcherPriority.ApplicationIdle);
    }

    private void Initialize()
    {
        try
        {
            var config = _store.LoadConfig();
            if (!config.PinConfigured)
            {
                throw new InvalidOperationException("Privacy PIN is not configured.");
            }

            var state = _store.LoadState();
            if (!state.Active || !string.Equals(state.LockId, _options.LockId, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("Privacy lock state no longer matches this helper session.");
            }

            foreach (var screen in Forms.Screen.AllScreens)
            {
                var window = new PrivacyLockOverlayWindow(screen);
                window.Show();
                var handle = new WindowInteropHelper(window).EnsureHandle();
                if (!SetWindowDisplayAffinity(handle, WDA_EXCLUDEFROMCAPTURE))
                {
                    throw new InvalidOperationException("Privacy overlay could not be excluded from capture on this Windows version.");
                }
                _windows.Add(window);
            }

            InstallHooks();
            UpdateWindows();

            state.HelperPid = Environment.ProcessId;
            state.HelperReady = true;
            state.HelperError = "";
            state.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            _store.SaveState(state);

            _statePollTimer.Start();
        }
        catch (Exception ex)
        {
            FailStart(ex.Message);
        }
    }

    private void InstallHooks()
    {
        var moduleHandle = GetModuleHandle(null);
        _keyboardHook = SetWindowsHookEx(WH_KEYBOARD_LL, _keyboardProc, moduleHandle, 0);
        if (_keyboardHook == IntPtr.Zero)
        {
            throw new InvalidOperationException("Could not install privacy keyboard hook.");
        }

        _mouseHook = SetWindowsHookEx(WH_MOUSE_LL, _mouseProc, moduleHandle, 0);
        if (_mouseHook == IntPtr.Zero)
        {
            throw new InvalidOperationException("Could not install privacy mouse hook.");
        }
    }

    private void UninstallHooks()
    {
        if (_keyboardHook != IntPtr.Zero)
        {
            UnhookWindowsHookEx(_keyboardHook);
            _keyboardHook = IntPtr.Zero;
        }

        if (_mouseHook != IntPtr.Zero)
        {
            UnhookWindowsHookEx(_mouseHook);
            _mouseHook = IntPtr.Zero;
        }
    }

    private void CheckRemoteUnlockState()
    {
        if (_shuttingDown)
        {
            return;
        }

        var state = _store.LoadState();
        if (!state.Active || !string.Equals(state.LockId, _options.LockId, StringComparison.Ordinal))
        {
            ShutdownHelper();
        }
    }

    private IntPtr KeyboardHookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode < 0)
        {
            return CallNextHookEx(IntPtr.Zero, nCode, wParam, lParam);
        }

        var info = Marshal.PtrToStructure<KBDLLHOOKSTRUCT>(lParam);
        var injected = (info.flags & LLKHF_INJECTED) != 0 || (info.flags & LLKHF_LOWER_IL_INJECTED) != 0;
        if (injected)
        {
            return CallNextHookEx(IntPtr.Zero, nCode, wParam, lParam);
        }

        var message = unchecked((int)(long)wParam);
        if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN)
        {
            WpfApplication.Current.Dispatcher.BeginInvoke(new Action(() => HandleLocalKey((int)info.vkCode)));
        }

        if (message == WM_KEYDOWN || message == WM_KEYUP || message == WM_SYSKEYDOWN || message == WM_SYSKEYUP)
        {
            return new IntPtr(1);
        }

        return CallNextHookEx(IntPtr.Zero, nCode, wParam, lParam);
    }

    private IntPtr MouseHookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode < 0)
        {
            return CallNextHookEx(IntPtr.Zero, nCode, wParam, lParam);
        }

        var info = Marshal.PtrToStructure<MSLLHOOKSTRUCT>(lParam);
        if ((info.flags & LLMHF_INJECTED) != 0)
        {
            return CallNextHookEx(IntPtr.Zero, nCode, wParam, lParam);
        }

        return new IntPtr(1);
    }

    private void HandleLocalKey(int vkCode)
    {
        if (_shuttingDown)
        {
            return;
        }

        if (vkCode >= 0x30 && vkCode <= 0x39 && _pinBuffer.Length < 12)
        {
            _detailText = "Please do not interrupt. Enter PIN to unlock locally.";
            _pinBuffer.Append((char)('0' + (vkCode - 0x30)));
            UpdateWindows();
            return;
        }

        if (vkCode >= VK_NUMPAD0 && vkCode <= VK_NUMPAD9 && _pinBuffer.Length < 12)
        {
            _detailText = "Please do not interrupt. Enter PIN to unlock locally.";
            _pinBuffer.Append((char)('0' + (vkCode - VK_NUMPAD0)));
            UpdateWindows();
            return;
        }

        switch (vkCode)
        {
            case VK_BACK:
                if (_pinBuffer.Length > 0)
                {
                    _pinBuffer.Length -= 1;
                }
                _detailText = "Please do not interrupt. Enter PIN to unlock locally.";
                UpdateWindows();
                return;
            case VK_ESCAPE:
                _pinBuffer.Clear();
                _detailText = "PIN entry cleared.";
                UpdateWindows();
                return;
            case VK_RETURN:
                SubmitPin();
                return;
            default:
                return;
        }
    }

    private void SubmitPin()
    {
        var candidate = _pinBuffer.ToString();
        _pinBuffer.Clear();
        if (!_store.VerifyPin(candidate))
        {
            _detailText = "Incorrect PIN. Try again.";
            UpdateWindows();
            return;
        }

        _detailText = "Unlocking laptop…";
        UpdateWindows();
        ReleaseFromLocalPin();
    }

    private void ReleaseFromLocalPin()
    {
        var state = _store.LoadState();
        state.Active = false;
        state.OwnerDeviceId = "";
        state.OwnerDeviceName = "";
        state.CallbackToken = "";
        state.HelperReady = false;
        state.HelperPid = 0;
        state.HelperError = "";
        state.LastUnlockSource = "local_pin";
        state.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        _store.SaveState(state);
        _ = NotifyControllerLocalUnlockAsync();
        ShutdownHelper();
    }

    private async Task NotifyControllerLocalUnlockAsync()
    {
        if (_options.ControllerPort <= 0 || string.IsNullOrWhiteSpace(_options.CallbackToken))
        {
            return;
        }

        try
        {
            using var client = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(2),
            };
            var payload = JsonSerializer.Serialize(new
            {
                lock_id = _options.LockId,
                callback_token = _options.CallbackToken,
                source = "local_pin",
            });
            using var response = await client.PostAsync(
                $"http://127.0.0.1:{_options.ControllerPort}/desktop/privacy-lock/internal/release",
                new StringContent(payload, Encoding.UTF8, "application/json"));
            _ = response.IsSuccessStatusCode;
        }
        catch
        {
        }
    }

    private void UpdateWindows()
    {
        var pinText = _pinBuffer.Length > 0
            ? $"PIN: {new string('•', _pinBuffer.Length)}"
            : "PIN: ";
        foreach (var window in _windows)
        {
            window.UpdateStatus(_detailText, pinText);
        }
    }

    private void ShutdownHelper()
    {
        if (_shuttingDown)
        {
            return;
        }

        _shuttingDown = true;
        _statePollTimer.Stop();
        UninstallHooks();
        foreach (var window in _windows.ToArray())
        {
            try
            {
                window.Close();
            }
            catch
            {
            }
        }
        _windows.Clear();
        WpfApplication.Current.Shutdown();
    }

    private void FailStart(string detail)
    {
        try
        {
            var state = _store.LoadState();
            if (string.Equals(state.LockId, _options.LockId, StringComparison.Ordinal))
            {
                state.Active = false;
                state.HelperReady = false;
                state.HelperPid = 0;
                state.HelperError = detail;
                state.CallbackToken = "";
                state.LastUnlockSource = "";
                state.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                _store.SaveState(state);
            }
        }
        catch
        {
        }

        WpfApplication.Current.Shutdown(1);
    }

    private delegate IntPtr LowLevelKeyboardProc(int nCode, IntPtr wParam, IntPtr lParam);
    private delegate IntPtr LowLevelMouseProc(int nCode, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KBDLLHOOKSTRUCT
    {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSLLHOOKSTRUCT
    {
        public POINT pt;
        public uint mouseData;
        public uint flags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, Delegate lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr GetModuleHandle(string? lpModuleName);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowDisplayAffinity(IntPtr hWnd, uint dwAffinity);
}
