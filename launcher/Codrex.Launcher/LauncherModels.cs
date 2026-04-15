using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Codrex.Launcher;

public sealed class LauncherPreferences
{
    [JsonPropertyName("preferred_pair_route")]
    public string PreferredPairRoute { get; set; } = "tailscale";

    [JsonPropertyName("advanced_visible")]
    public bool AdvancedVisible { get; set; }

    [JsonPropertyName("minimize_to_tray")]
    public bool MinimizeToTray { get; set; } = true;
}

public sealed class RuntimeActionResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("action")]
    public string Action { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("detail")]
    public string Detail { get; set; } = "";

    [JsonPropertyName("repo_root")]
    public string RepoRoot { get; set; } = "";

    [JsonPropertyName("repo_rev")]
    public string RepoRev { get; set; } = "";

    [JsonPropertyName("runtime_dir")]
    public string RuntimeDir { get; set; } = "";

    [JsonPropertyName("logs_dir")]
    public string LogsDir { get; set; } = "";

    [JsonPropertyName("controller_port")]
    public int ControllerPort { get; set; }

    [JsonPropertyName("session_present")]
    public bool SessionPresent { get; set; }

    [JsonPropertyName("app_ready")]
    public bool AppReady { get; set; }

    [JsonPropertyName("app_version")]
    public string AppVersion { get; set; } = "";

    [JsonPropertyName("ui_mode")]
    public string UiMode { get; set; } = "";

    [JsonPropertyName("local_url")]
    public string LocalUrl { get; set; } = "";

    [JsonPropertyName("network_url")]
    public string NetworkUrl { get; set; } = "";

    [JsonPropertyName("controller_mode")]
    public string ControllerMode { get; set; } = "";

    [JsonPropertyName("sessions_runtime_state")]
    public string SessionsRuntimeState { get; set; } = "";

    [JsonPropertyName("action_id")]
    public string ActionId { get; set; } = "";

    [JsonPropertyName("diagnostic_log_path")]
    public string DiagnosticLogPath { get; set; } = "";

    [JsonPropertyName("last_action_path")]
    public string LastActionPath { get; set; } = "";

    [JsonPropertyName("last_error_path")]
    public string LastErrorPath { get; set; } = "";
}

public sealed class RouteOriginPayload
{
    [JsonPropertyName("provider")]
    public string Provider { get; set; } = "";

    [JsonPropertyName("host")]
    public string Host { get; set; } = "";

    [JsonPropertyName("origin")]
    public string Origin { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";
}

public sealed class NetInfoPayload
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("lan_ip")]
    public string LanIp { get; set; } = "";

    [JsonPropertyName("tailscale_ip")]
    public string TailscaleIp { get; set; } = "";

    [JsonPropertyName("netbird_ip")]
    public string NetbirdIp { get; set; } = "";

    [JsonPropertyName("preferred_origin")]
    public string PreferredOrigin { get; set; } = "";

    [JsonPropertyName("route_provider")]
    public string RouteProvider { get; set; } = "";

    [JsonPropertyName("route_state")]
    public string RouteState { get; set; } = "";

    [JsonPropertyName("available_origins")]
    public List<RouteOriginPayload> AvailableOrigins { get; set; } = new();
}

public sealed class PairCreatePayload
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("code")]
    public string Code { get; set; } = "";

    [JsonPropertyName("expires_in")]
    public int ExpiresIn { get; set; }

    [JsonPropertyName("detail")]
    public string Detail { get; set; } = "";

    [JsonPropertyName("error")]
    public string Error { get; set; } = "";
}

public sealed class PairingResult
{
    public bool Ok { get; set; }
    public string Detail { get; set; } = "";
    public string PairLink { get; set; } = "";
    public string QrImageUrl { get; set; } = "";
    public int ExpiresIn { get; set; }
}

public sealed class ControllerConfigData
{
    public int Port { get; set; } = 48787;
    public string Token { get; set; } = "";
}

public sealed class LauncherPrivacyLockStatus
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("supported")]
    public bool Supported { get; set; }

    [JsonPropertyName("detail")]
    public string Detail { get; set; } = "";

    [JsonPropertyName("pin_configured")]
    public bool PinConfigured { get; set; }

    [JsonPropertyName("active")]
    public bool Active { get; set; }

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "";

    [JsonPropertyName("display_scope")]
    public string DisplayScope { get; set; } = "";

    [JsonPropertyName("owner_device_name")]
    public string OwnerDeviceName { get; set; } = "";

    [JsonPropertyName("helper_ready")]
    public bool HelperReady { get; set; }

    [JsonPropertyName("helper_error")]
    public string HelperError { get; set; } = "";

    [JsonPropertyName("last_unlock_source")]
    public string LastUnlockSource { get; set; } = "";
}

public sealed class LauncherAccountAuthProfile
{
    [JsonPropertyName("account_id")]
    public string AccountId { get; set; } = "";

    [JsonPropertyName("email")]
    public string Email { get; set; } = "";

    [JsonPropertyName("plan_type")]
    public string PlanType { get; set; } = "";

    [JsonPropertyName("subscription_active_until")]
    public string SubscriptionActiveUntil { get; set; } = "";

    [JsonPropertyName("subscription_last_checked")]
    public string SubscriptionLastChecked { get; set; } = "";
}

public sealed class LauncherAccountUsage
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("context_left")]
    public string ContextLeft { get; set; } = "";

    [JsonPropertyName("weekly_left")]
    public string WeeklyLeft { get; set; } = "";

    [JsonPropertyName("tip")]
    public string Tip { get; set; } = "";

    [JsonPropertyName("detail")]
    public string Detail { get; set; } = "";

    [JsonPropertyName("stale")]
    public bool Stale { get; set; }

    [JsonPropertyName("probed_at")]
    public long ProbedAt { get; set; }
}

public sealed class LauncherAccountSummary
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("codex_home")]
    public string CodexHome { get; set; } = "";

    [JsonPropertyName("implicit_primary")]
    public bool ImplicitPrimary { get; set; }

    [JsonPropertyName("created_at")]
    public long CreatedAt { get; set; }

    [JsonPropertyName("last_used_at")]
    public long LastUsedAt { get; set; }

    [JsonPropertyName("active")]
    public bool Active { get; set; }

    [JsonPropertyName("auth_profile")]
    public LauncherAccountAuthProfile? AuthProfile { get; set; }

    [JsonPropertyName("usage")]
    public LauncherAccountUsage? Usage { get; set; }
}

public sealed class LauncherAccountsPayload
{
    [JsonPropertyName("active_account_id")]
    public string ActiveAccountId { get; set; } = "";

    [JsonPropertyName("real_codex_path")]
    public string RealCodexPath { get; set; } = "";

    [JsonPropertyName("accounts")]
    public List<LauncherAccountSummary> Accounts { get; set; } = new();
}

public sealed class LauncherAccountActivateResult
{
    [JsonPropertyName("active_account_id")]
    public string ActiveAccountId { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("codex_home")]
    public string CodexHome { get; set; } = "";
}
