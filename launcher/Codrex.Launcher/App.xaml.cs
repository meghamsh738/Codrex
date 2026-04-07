using System.Threading;
using System.Windows;
using System.Windows.Threading;

namespace Codrex.Launcher;

public partial class App : Application
{
    private const string LauncherMutexName = "Codrex.Launcher.Singleton";
    private const string LauncherActivateEventName = "Codrex.Launcher.Activate";

    private Mutex? _instanceMutex;
    private EventWaitHandle? _activateEvent;
    private CancellationTokenSource? _activateCts;
    private Task? _activateTask;

    protected override void OnStartup(StartupEventArgs e)
    {
        var createdNew = false;
        _instanceMutex = new Mutex(true, LauncherMutexName, out createdNew);
        if (!createdNew)
        {
            SignalExistingInstance();
            Shutdown();
            return;
        }

        _activateEvent = new EventWaitHandle(false, EventResetMode.AutoReset, LauncherActivateEventName);
        _activateCts = new CancellationTokenSource();
        _activateTask = Task.Run(() => WaitForActivationSignalAsync(_activateCts.Token));

        ShutdownMode = ShutdownMode.OnMainWindowClose;
        MainWindow = new MainWindow();
        MainWindow.Show();
        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _activateCts?.Cancel();
        try
        {
            _activateEvent?.Set();
        }
        catch
        {
        }

        if (_activateTask is not null)
        {
            try
            {
                _activateTask.Wait(TimeSpan.FromMilliseconds(500));
            }
            catch
            {
            }
        }

        _activateEvent?.Dispose();
        _activateCts?.Dispose();
        if (_instanceMutex is not null)
        {
            try
            {
                _instanceMutex.ReleaseMutex();
            }
            catch (ApplicationException)
            {
            }
            _instanceMutex.Dispose();
        }

        base.OnExit(e);
    }

    private static void SignalExistingInstance()
    {
        try
        {
            using var activateEvent = EventWaitHandle.OpenExisting(LauncherActivateEventName);
            activateEvent.Set();
        }
        catch
        {
        }
    }

    private async Task WaitForActivationSignalAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            _activateEvent?.WaitOne();
            if (cancellationToken.IsCancellationRequested)
            {
                break;
            }

            await Dispatcher.InvokeAsync(ActivateMainWindow, DispatcherPriority.ApplicationIdle, cancellationToken);
        }
    }

    private void ActivateMainWindow()
    {
        var window = MainWindow;
        if (window is null)
        {
            return;
        }

        if (!window.IsVisible)
        {
            window.Show();
        }

        if (window.WindowState == WindowState.Minimized)
        {
            window.WindowState = WindowState.Normal;
        }

        window.Topmost = true;
        window.Topmost = false;
        window.Activate();
        window.Focus();
    }
}
