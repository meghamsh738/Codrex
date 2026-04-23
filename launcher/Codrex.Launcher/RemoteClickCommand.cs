using System.Runtime.InteropServices;
using System.Threading;

namespace Codrex.Launcher;

internal sealed class RemoteClickOptions
{
    public int X { get; init; }
    public int Y { get; init; }
    public string Button { get; init; } = "left";
    public string Action { get; init; } = "click";
    public bool DoubleClick { get; init; }
}

internal static class RemoteClickCommand
{
    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    private const uint MOUSEEVENTF_RIGHTUP = 0x0010;
    private const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
    private const uint MOUSEEVENTF_MIDDLEUP = 0x0040;

    public static bool TryParse(string[] args, out RemoteClickOptions? options)
    {
        options = null;
        if (args.Length == 0 || !string.Equals(args[0], "--remote-click", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (args.Length < 3 || !int.TryParse(args[1], out var x) || !int.TryParse(args[2], out var y))
        {
            throw new ArgumentException("Remote click requires x and y coordinates.");
        }

        var button = "left";
        var action = "click";
        var doubleClick = false;
        for (var index = 3; index < args.Length; index += 1)
        {
            var arg = args[index];
            if (string.Equals(arg, "--double", StringComparison.OrdinalIgnoreCase))
            {
                doubleClick = true;
                continue;
            }

            if (index + 1 >= args.Length)
            {
                break;
            }

            if (string.Equals(arg, "--button", StringComparison.OrdinalIgnoreCase))
            {
                button = args[index + 1];
                index += 1;
                continue;
            }

            if (string.Equals(arg, "--action", StringComparison.OrdinalIgnoreCase))
            {
                action = args[index + 1];
                index += 1;
            }
        }

        options = new RemoteClickOptions
        {
            X = x,
            Y = y,
            Button = button,
            Action = action,
            DoubleClick = doubleClick,
        };
        return true;
    }

    public static int Execute(RemoteClickOptions options)
    {
        EnsureDpiAwareness();
        if (!SetCursorPos(options.X, options.Y))
        {
            return Marshal.GetLastWin32Error() != 0 ? Marshal.GetLastWin32Error() : 1;
        }

        Thread.Sleep(90);

        var button = (options.Button ?? "left").Trim().ToLowerInvariant();
        var action = (options.Action ?? "click").Trim().ToLowerInvariant();
        var mapping = button switch
        {
            "left" => (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right" => (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle" => (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
            _ => (0u, 0u),
        };
        if (mapping.Item1 == 0 || mapping.Item2 == 0)
        {
            return 2;
        }

        if (action == "down")
        {
            mouse_event(mapping.Item1, 0, 0, 0, UIntPtr.Zero);
            return 0;
        }

        if (action == "up")
        {
            mouse_event(mapping.Item2, 0, 0, 0, UIntPtr.Zero);
            return 0;
        }

        var times = options.DoubleClick ? 2 : 1;
        for (var i = 0; i < times; i += 1)
        {
            mouse_event(mapping.Item1, 0, 0, 0, UIntPtr.Zero);
            mouse_event(mapping.Item2, 0, 0, 0, UIntPtr.Zero);
            if (times > 1 && i == 0)
            {
                Thread.Sleep(60);
            }
        }

        return 0;
    }

    private static void EnsureDpiAwareness()
    {
        try
        {
            var contextValue = unchecked((nint)(-4));
            if (SetProcessDpiAwarenessContext(contextValue))
            {
                return;
            }
        }
        catch
        {
        }

        try
        {
            _ = SetProcessDPIAware();
        }
        catch
        {
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetProcessDpiAwarenessContext(nint dpiContext);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetProcessDPIAware();
}
