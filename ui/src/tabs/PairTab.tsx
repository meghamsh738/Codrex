import type { NetInfo } from "../types";

type RouteHint = "lan" | "tailscale" | "current";

interface PairTabProps {
  screenCardClassName: string;
  routeHint: RouteHint;
  prettyRouteLabel: (route: RouteHint) => string;
  isLocalBrowser: boolean;
  controllerBase: string;
  setControllerBase: (value: string) => void;
  onRouteHintChange: (route: RouteHint) => void;
  netInfo: NetInfo | null;
  tailscaleRouteUnavailable: boolean;
  pairBusy: boolean;
  onGeneratePairing: () => void;
  refreshNet: () => void;
  onPairExchange: () => void;
  pairCode: string;
  pairExpiry: number | null;
  pairLink: string;
  onCopyPairLink: () => void;
  onOpenPairLink: () => void;
  pairQrUrl: string;
}

export default function PairTab({
  screenCardClassName,
  routeHint,
  prettyRouteLabel,
  isLocalBrowser,
  controllerBase,
  setControllerBase,
  onRouteHintChange,
  netInfo,
  tailscaleRouteUnavailable,
  pairBusy,
  onGeneratePairing,
  refreshNet,
  onPairExchange,
  pairCode,
  pairExpiry,
  pairLink,
  onCopyPairLink,
  onOpenPairLink,
  pairQrUrl,
}: PairTabProps) {
  return (
    <section className={screenCardClassName} data-testid="tab-panel-pair">
      <div className="card-head">
        <h2>Pair Device</h2>
        <div className="row">
          <span className="badge">QR Flow</span>
          <span className="badge muted">{prettyRouteLabel(routeHint)}</span>
        </div>
      </div>

      <div className="pair-layout">
        <div className="stack">
          <p className="small">
            Keep using Tailscale + token auth. QR exchange only grants this device the existing backend token context.
          </p>

          <div className="step-card">
            <div className="step-head">
              <span className="step-index">1</span>
              <h3>Choose Route</h3>
            </div>
            <label className="field">
              <span>Route Hint</span>
              <select
                data-testid="pair-route-hint-select"
                value={routeHint}
                onChange={(event) => onRouteHintChange(event.target.value as RouteHint)}
              >
                <option value="tailscale">{prettyRouteLabel("tailscale")} (default)</option>
                <option value="lan" disabled={!isLocalBrowser}>
                  {prettyRouteLabel("lan")}{!isLocalBrowser ? " (localhost only)" : ""}
                </option>
                <option value="current" disabled={!isLocalBrowser}>
                  {prettyRouteLabel("current")}{!isLocalBrowser ? " (localhost only)" : ""}
                </option>
              </select>
            </label>
            {!isLocalBrowser ? (
              <p className="small warn">
                For safety, LAN/current pairing routes are disabled outside localhost browser sessions.
              </p>
            ) : null}
            <label className="field">
              <span>Controller Base URL</span>
              <input
                type="text"
                value={controllerBase}
                onChange={(event) => setControllerBase(event.target.value)}
                placeholder="http://192.168.x.x:<codrex-port>"
              />
            </label>
            <p className="small">
              LAN: <strong>{netInfo?.lan_ip || "n/a"}</strong> | Tailscale: <strong>{netInfo?.tailscale_ip || "n/a"}</strong>
            </p>
            {tailscaleRouteUnavailable ? (
              <p className="small warn">Tailscale route is selected but no Tailscale IP is detected.</p>
            ) : null}
          </div>

          <div className="step-card">
            <div className="step-head">
              <span className="step-index">2</span>
              <h3>Generate and Exchange</h3>
            </div>
            <div className="row">
              <button type="button" className="button" onClick={() => void onGeneratePairing()} disabled={pairBusy}>
                {pairBusy ? "Generating..." : "Generate QR"}
              </button>
              <button type="button" className="button soft compact" onClick={() => void refreshNet()}>
                Refresh Routes
              </button>
              <button type="button" className="button soft compact" onClick={() => void onPairExchange()} disabled={pairBusy || !pairCode}>
                Exchange Here
              </button>
            </div>
            <p className="small">Generate QR first, then use Exchange Here on this device if needed.</p>
          </div>
        </div>

        <div className="pair-preview">
          {pairCode ? (
            <>
              <div className="step-head">
                <span className="step-index">3</span>
                <h3>Scan or Share</h3>
              </div>
              <p className="small">
                Code: <code>{pairCode}</code>
                {pairExpiry ? ` (expires in ${pairExpiry}s)` : ""}
              </p>
              <textarea data-testid="pair-link-text" readOnly value={pairLink} rows={3} />
              <div className="row">
                <button type="button" className="button soft compact" onClick={() => void onCopyPairLink()}>
                  Copy Link
                </button>
                <button type="button" className="button soft compact" onClick={onOpenPairLink}>
                  Open Link
                </button>
              </div>
              {pairQrUrl ? (
                <div className="pair-qr-wrap">
                  <img className="qr" src={pairQrUrl} alt="Pairing QR" />
                </div>
              ) : null}
            </>
          ) : (
            <div className="empty-state panel-empty">
              <h3>No code generated</h3>
              <p>Generate a pairing code to show a QR image for phone/tablet sign-in.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
