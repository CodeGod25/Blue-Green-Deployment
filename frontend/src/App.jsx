import React, { useState, useEffect } from 'react';
import {
  Shield, Activity, Clock, Server, Layout,
  Terminal, Home, Flame, Globe, X,
  CheckCircle2, AlertCircle, ChevronRight,
  ShieldAlert, Database, Zap, Rocket, HelpCircle,
  RotateCcw
} from 'lucide-react';

// ── Health Monitor Component ──
function HealthGrid({ services }) {
  const safeServices = (services && typeof services === 'object' && !Array.isArray(services)) ? services : {};
  return (
    <div className="health-grid">
      {Object.entries(safeServices).map(([name, svc]) => (
        <div key={name} className={`health-item ${svc.healthy ? 'is-up' : 'is-down'}`}>
          <div className="hi-icon">
            {name === 'proxy' ? <Globe size={18} /> : <Server size={18} />}
          </div>
          <div className="hi-body">
            <div className="hi-name">{name.toUpperCase()}</div>
            <div className="hi-meta">
              <span className="hi-pulse" />
              {svc.healthy ? `${svc.latencyMs}ms` : 'OFFLINE'}
            </div>
          </div>
          {svc.healthy && (
            <a href={name === 'proxy' ? '/' : `/${name}/`} target="_blank" rel="noopener noreferrer" className="hi-link" title="Open App">
              <ChevronRight size={14} />
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Preflight Readiness Component ──
function PreflightChecks({ checks }) {
  const safeChecks = Array.isArray(checks) ? checks : [];
  const passedCount = safeChecks.filter(c => c.passed).length;
  const isReady = passedCount === safeChecks.length && safeChecks.length > 0;

  return (
    <div className="preflight-panel glass-panel">
      <div className="panel-header">
        <h2>System Preflight</h2>
        <span className={`panel-badge ${isReady ? 'ok' : 'warn'}`}>
          {passedCount}/{checks.length} READY
        </span>
      </div>
      <div className="check-list">
        {safeChecks.map((c, i) => (
          <div key={i} className={`check-item ${c.passed ? 'cp-pass' : 'cp-fail'}`}>
            <div className="ci-icon">
              {c.passed ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
            </div>
            <div className="ci-body">
              <div className="ci-label">{c.name}</div>
              <div className="ci-detail">{c.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main App ──
export default function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [showSidebar, setShowSidebar] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    let eventSource;
    let reconnectTimeout;
    let pollInterval;

    const fetchInitialStatus = async () => {
      try {
        const res = await fetch('/api/status');
        if (res.ok) {
          const data = await res.json();
          setStatus(data);
        }
      } catch (err) {
        console.error("Initial Telemetry Fetch Failed:", err);
      }
    };

    const connect = () => {
      if (eventSource) eventSource.close();
      console.log("Connecting to Titanium Telemetry Stream...");
      eventSource = new EventSource('/api/events/stream');

      eventSource.addEventListener('status', (event) => {
        try {
          const data = JSON.parse(event.data);
          setStatus(data);
          setError(null);
          // If SSE works, we can stop polling
          if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
          }
        } catch (err) {
          console.error("Telemetry Parse Error:", err);
        }
      });

      eventSource.onerror = (err) => {
        console.warn("Telemetry Stream Interrupted. Fallback to Polling...");
        // Suppress visual error if we have data or are just retrying
        if (!status) setError("Telemetry Stream Interrupted");
        eventSource.close();

        // Start polling if not already polling
        if (!pollInterval) {
          pollInterval = setInterval(fetchInitialStatus, 5000);
        }

        reconnectTimeout = setTimeout(connect, 10000); // Try SSE again in 10s
      };
    };

    fetchInitialStatus();
    connect();

    return () => {
      if (eventSource) eventSource.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (pollInterval) clearInterval(pollInterval);
    };
  }, []);

  if (!status) return (
    <div className="loader-box">
      <div className="loader-titanium" />
      <p>Initializing Titanium Control Plane...</p>
      {error && <div className="loader-error-msg">{error}</div>}
    </div>
  );

  const {
    metrics = {},
    services = {},
    devops = {},
    events = [],
    history = {}
  } = status || {};

  const activeTarget = (status?.active?.target || 'unknown').toUpperCase();
  const activeEnv = activeTarget === 'UNKNOWN' ? 'IDLE' : activeTarget;
  const checks = devops?.checks || [];

  const handleChaos = (mode) => {
    fetch('/api/chaos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });
  };

  const handlePromote = () => {
    fetch('/api/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: status?.devops?.nextTarget || 'green' })
    });
  };

  const sr = metrics?.success_rate ?? 100;

  // Globally derived history timeline for all views (Fixes ReferenceErrors)
  const timeline = Array.isArray(history?.last60s) ? history.last60s : [];
  const rpsHistory = timeline.map(p => p.rps || 0);
  const latencyHistory = timeline.map(p => p.latencyMs || 0);
  const successHistory = timeline.map(p => (p.code === 200 ? 100 : 0));

  return (
    <div className="app titanium-theme">
      {/* ── Help Overlay ── */}
      {showHelp && (
        <div className="help-overlay animate-fade" onClick={() => setShowHelp(false)}>
          <div className="help-modal glass-panel" onClick={e => e.stopPropagation()}>
            <div className="panel-header">
              <h2>Project Titanium Guide</h2>
              <button className="sidebar-close" onClick={() => setShowHelp(false)}><X size={20} /></button>
            </div>
            <div className="help-content">
              <p><strong>1. Monitor Health:</strong> Track RPS and Latency in real-time.</p>
              <p><strong>2. Shift Traffic:</strong> Use the Canary slider in Infrastructure.</p>
              <p><strong>3. Promote Release:</strong> Finalize swaps with the Promotion button.</p>
              <p><strong>4. Real Chaos:</strong> Stop or Pause containers in the Chaos Lab.</p>
            </div>
          </div>
        </div>
      )}
      
      {/* ── Chaos Interference Banner ── */}
      {status?.devops?.chaos?.active && (
        <div className="chaos-banner-global animate-pulse">
          <div className="cb-inner">
            <ShieldAlert size={16} />
            <span>SYSTEM INTERFERENCE ACTIVE · FAULT INJECTION MODE: {status.devops.chaos.mode.toUpperCase()} · ERRORS EXPECTED</span>
          </div>
        </div>
      )}

      {/* ── Top Bar ── */}
      <header className={`topbar env-${activeEnv.toLowerCase()}`}>
        <div className="topbar-left">
          <div className="brand" onClick={() => setActiveTab('overview')} style={{ cursor: 'pointer' }}>
            <Shield size={20} className="brand-hex" />
            <span className="brand-name">PROJECT TITANIUM</span>
          </div>
        </div>
        <div className="topbar-right">
          <div className={`pill ${activeEnv === 'BLUE' ? 'pill-blue' : 'pill-green'}`}>
            <Server size={12} /> ACTIVE: {activeEnv}
          </div>
          {status?.devops?.chaos?.active && (
            <div className="pill pill-chaos blink-fast">
              <ShieldAlert size={12} /> CHAOS: {status.devops.chaos.mode.toUpperCase()}
            </div>
          )}
          <ConnectivityProbe />
          <div className={`pill ${sr < 99 ? 'pill-err' : 'pill-ok'}`}>
            <span className="blink-dot" />
            {sr}% SUCCESS RATE
          </div>
          <button className="help-trigger-btn" onClick={() => setShowHelp(true)}>
            <HelpCircle size={16} />
          </button>
          <button className="preview-trigger" onClick={() => setShowSidebar(!showSidebar)}>
            <Layout size={16} /> LIVE PREVIEW
          </button>
        </div>
      </header>

      <div className="dash-layout">
        {/* ── Sidebar ── */}
        <aside className="sidebar">
          <div className="sidebar-group">
            <SidebarItem icon={<Home size={18} />} label="Overview" active={activeTab === 'overview'} onClick={() => setActiveTab('overview')} />
            <SidebarItem icon={<Server size={18} />} label="Infrastructure" active={activeTab === 'infra'} onClick={() => setActiveTab('infra')} />
            <SidebarItem icon={<Shield size={18} />} label="Security & Guardrails" active={activeTab === 'security'} onClick={() => setActiveTab('security')} />
            <SidebarItem icon={<Flame size={18} />} label="Chaos Lab" active={activeTab === 'chaos'} onClick={() => setActiveTab('chaos')} />
            <SidebarItem icon={<Terminal size={18} />} label="System Logs" active={activeTab === 'logs'} onClick={() => setActiveTab('logs')} />
          </div>
        </aside>

        {/* ── Main Content Switcher ── */}
        <main className="dash-main">
          {activeTab === 'overview' && (
            <OverviewView
              status={status}
              activeEnv={activeEnv}
              rpsHistory={rpsHistory}
              latencyHistory={latencyHistory}
              successHistory={successHistory}
            />
          )}
          {activeTab === 'infra' && <InfrastructureView services={services} checks={checks} status={status} onPromote={handlePromote} />}
          {activeTab === 'security' && <SecurityView events={events} metrics={metrics} />}
          {activeTab === 'chaos' && (
            <ChaosView
              status={status}
              metrics={metrics}
              activeEnv={activeEnv}
              onInject={handleChaos}
              activeMode={status?.devops?.chaos?.mode || 'none'}
              rpsHistory={rpsHistory}
              latencyHistory={latencyHistory}
              successHistory={successHistory}
            />
          )}
          {activeTab === 'logs' && <LogsView events={events} />}


          <footer className="dash-footer">
            <Shield size={12} /> TitaniumOps · MISSION READY · 2026
          </footer>
        </main>

        {/* ── LIVE PREVIEW SIDEBAR ── */}
        <div className={`websites-sidebar titanium-sidebar ${showSidebar ? 'sidebar-open' : 'sidebar-closed'}`}>
          <div className="sidebar-header">
            <h3 className="section-title">Live Preview</h3>
            <button className="sidebar-close" onClick={() => setShowSidebar(false)}><X size={16} /></button>
          </div>
          <div className="websites-container">
            <div className="website-viewer panel">
              <div className="website-header">
                <span className="label-blue">BLUE DEPLOYMENT (v1.0)</span>
              </div>
              <iframe src="/blue/" className="website-frame" title="Blue Preview" />
            </div>
            <div className="website-viewer panel">
              <div className="website-header">
                <span className="label-green">GREEN DEPLOYMENT (v2.0)</span>
              </div>
              <iframe src="/green/" className="website-frame" title="Green Preview" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Views ─────────────────────────── */

function OverviewView({ status, activeEnv, rpsHistory, latencyHistory, successHistory }) {
  const metrics = status?.metrics || {};
  const sr = metrics?.success_rate ?? 100;

  // Use props instead of local derivation to maintain consistency across tabs

  // If rps isn't in timeline, we can use a moving window average or just fallback
  // Actually, let's just use the metrics.rps as a baseline if timeline is short

  return (
    <div className="view-container animate-fade">
      <header className="hero-section">
        <div className={`hero hero-${activeEnv || 'idle'}`}>
          <div className="hero-left">
            <div className="hero-eyebrow">ACTIVE ENGINE</div>
            <div className="hero-env">{activeEnv?.toUpperCase() || 'STANDBY'}</div>
            <div className="hero-sub">
              <span className="tag-mono">Release v2.1.0-titanium</span>
              <span className="hero-since">Last Sync: {new Date().toLocaleTimeString()}</span>
            </div>
          </div>
          <div className="hero-right">
            <div className="hero-how">
              <div className="how-step"><div className="how-num">1</div> <strong>Monitor</strong> infrastructure health real-time.</div>
              <div className="how-step"><div className="how-num">2</div> <strong>Shift Traffic</strong> safely via Canary controls.</div>
              <div className="how-step"><div className="how-num">3</div> <strong>Test Resilience</strong> with Chaos injection.</div>
            </div>
          </div>
        </div>
      </header>

      <div className="metrics-row">
        <MetricCard icon={<Activity size={16} />} value={metrics.rps ?? '—'} label="Req / Sec" sparkline={<Sparkline data={rpsHistory} color="var(--blue)" />} />
        <MetricCard icon={<Clock size={16} />} value={`${metrics.lastLatencyMs ?? '0'}ms`} label="P50 Latency" sparkline={<Sparkline data={latencyHistory} color="#818cf8" />} />
        <MetricCard icon={<Shield size={16} />} value={`${sr}%`} label="Success Rate" bar={sr} accent={sr < 99 ? 'red' : 'green'} sparkline={<Sparkline data={successHistory} color={sr < 99 ? 'var(--red)' : 'var(--green)'} />} />
      </div>

      <div className="main-grid">
        <div className="panel glass-panel">
          <div className="panel-header">
            <h2>Traffic Visualization</h2>
            <span className="panel-tag">Live Path</span>
          </div>
          <TrafficFlow active={activeEnv?.toLowerCase()} chaosActive={status?.devops?.chaos?.active} weights={status?.devops?.canary?.weights} />
        </div>
        <div className="panel glass-panel">
          <div className="panel-header">
            <h2>Orchestration Events</h2>
            <span className="panel-tag">Live Audit</span>
          </div>
          <div className="audit-log">
            {status.events?.slice(0, 15).map((e, idx) => (
              <div key={idx} className={`audit-entry ae-${e.level?.toLowerCase()}`}>
                <div className="ae-icon">
                  {e.event_type?.includes('CHAOS') ? <Flame size={14} /> :
                    e.event_type?.includes('ROLLBACK') ? <ShieldAlert size={14} /> :
                      e.event_type?.includes('DEPLOY') ? <Rocket size={14} /> : <Activity size={14} />}
                </div>
                <div className="ae-body">
                  <div className="ae-header">
                    <span className="ae-type">{e.event_type?.replace('_', ' ')}</span>
                    <span className="ae-time">{new Date(e.timestamp).toLocaleTimeString()}</span>
                  </div>
                  <p className="ae-msg">{e.message}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function InfrastructureView({ services, checks, status, onPromote }) {
  const metrics = status?.metrics || {};
  const canary = status?.devops?.canary || {};
  const events = status?.events || [];

  // Real metric derivations from backend status
  const activeRequests = metrics.totalRequests > 0 ? Math.floor((metrics.rps || 0) * (metrics.lastLatencyMs / 500)) : 0;
  const workerLoad = metrics.rps ? Math.min(100, (metrics.rps / 25) * 100).toFixed(1) : "0.0";

  // Uptime since last deployment/restart
  const lastSwitchStr = status?.active?.changedAt || status?.timestamp;
  const uptimeHours = lastSwitchStr ? ((new Date() - new Date(lastSwitchStr)) / 3600000).toFixed(1) : "0.0";

  return (
    <div className="view-container animate-fade">
      <div className="infra-layout">
        <div className="infra-left">
          <div className="panel titanium-panel">
            <div className="panel-header">
              <h2>Service Topology Map</h2>
              <span className="panel-tag">Connectivity Matrix</span>
            </div>
            <HealthGrid services={services} />
          </div>

          <PreflightChecks checks={checks} />

          <div className="panel glass-panel">
            <div className="panel-header">
              <h2>Nginx Upstream State</h2>
              <span className="panel-tag">Active Weighting</span>
            </div>
            <div className="terminal-inline">
              <pre>{`upstream titanium_cluster {\n  server blue_svc:80 weight=${status?.devops?.canary?.weights?.blue ?? 100};\n  server green_svc:80 weight=${status?.devops?.canary?.weights?.green ?? 0};\n  keepalive 32;\n}`}</pre>
            </div>
          </div>
        </div>

        <div className="infra-right">
          <div className="panel titanium-panel promotion-panel active-highlight">
            <div className="panel-header">
              <h2>Release Promotion</h2>
              <span className="panel-tag tag-primary">Live Control</span>
            </div>
            <div className="promo-body">
              <p>Promote the current <strong>{status?.devops?.nextTarget?.toUpperCase()}</strong> release to 100% production traffic.</p>
              <div className="promo-actions">
                <button
                  className="btn btn-primary promote-btn"
                  onClick={onPromote}
                >
                  <Rocket size={18} /> PROMOTE TO PRODUCTION
                </button>
                {!status?.devops?.preflightReady && (
                  <div className="promo-blocker">
                    <ShieldAlert size={14} />
                    <span>Unsafe Transition: Health checks failing</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <CanaryControl canary={status?.devops?.canary || {}} onUpdate={(w) => fetch('/api/canary', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(w) })} />

          <div className="panel glass-panel history-panel">
            <div className="panel-header">
              <h2>Steering History</h2>
              <span className="panel-tag">Action Audit</span>
            </div>
            <div className="history-list">
              {events.filter(e => e.message?.includes('Shifted traffic')).reverse().slice(0, 5).map((e, idx) => (
                <div key={idx} className="history-item">
                  <span className="h-time">{new Date(e.timestamp).toLocaleTimeString()}</span>
                  <span className="h-msg">{e.message}</span>
                </div>
              ))}
              {events.filter(e => e.message?.includes('Shifted traffic')).length === 0 && <p className="no-history">No traffic shifts recorded.</p>}
            </div>
          </div>

          <div className="panel glass-panel app-links-panel">
            <div className="panel-header">
              <h2>Direct Service Access</h2>
              <span className="panel-tag">Internal Verification</span>
            </div>
            <div className="app-link-grid">
              <a href="/app/" target="_blank" className="app-link-box al-prod">
                <Rocket size={20} /> <span>Live Production Site</span>
              </a>
              <a href="/blue/" target="_blank" className="app-link-box al-blue">
                <Layout size={20} /> <span>Verify Blue (v1.0)</span>
              </a>
              <a href="/green/" target="_blank" className="app-link-box al-green">
                <Layout size={20} /> <span>Verify Green (v2.0)</span>
              </a>
            </div>
          </div>

          <div className="panel glass-panel">
            <div className="panel-header">
              <h2>Cluster Telemetry</h2>
              <span className="panel-tag">Advanced Metrics</span>
            </div>
            <div className="stat-grid">
              <div className="s-box"><h4>Live Connections</h4><p>{activeRequests}</p></div>
              <div className="s-box"><h4>Cluster Load</h4><p>{workerLoad}%</p></div>
              <div className="s-box"><h4>System Uptime</h4><p>{uptimeHours}h</p></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SecurityView({ events, metrics }) {
  const safeEvents = Array.isArray(events) ? events : [];
  const safetyEvents = safeEvents.filter(e => e.eventType?.includes('GUARD') || e.level === 'WARN' || e.level === 'ERROR');
  return (
    <div className="view-container animate-fade">
      <div className="security-dashboard">
        <div className="panel glass-panel sec-overview">
          <ShieldAlert size={32} color="var(--green)" />
          <div>
            <h2>Guardrail Status: ACTIVE</h2>
            <p>Titanium Safety Loop is monitoring P50 Drift (&gt;500ms) and Error Rates (&gt;5%).</p>
          </div>
        </div>

        <div className="panel glass-panel">
          <div className="panel-header">
            <h2>Safety Trigger Audit</h2>
            <span className="panel-tag">Autonomous History</span>
          </div>
          <div className="safety-log">
            {safetyEvents.length > 0 ? safetyEvents.map((e, idx) => (
              <div key={idx} className="safety-item">
                <div className={`si-indicator si-${e.level?.toLowerCase()}`} />
                <div className="si-body">
                  <strong>{e.eventType}</strong>
                  <p>{e.message}</p>
                  <small>{new Date(e.timestamp).toLocaleString()}</small>
                </div>
              </div>
            )) : (
              <div className="no-data">
                <CheckCircle2 size={32} color="var(--green)" style={{ opacity: 0.2, marginBottom: '1rem' }} />
                <p>No safety violations detected. Infrastructure is nominal.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ChaosView({ status, metrics, activeEnv, onInject, activeMode, rpsHistory, latencyHistory, successHistory }) {
  const sr = Math.max(0, metrics?.success_rate ?? 100);

  return (
    <div className="view-container animate-fade">
      <div className="chaos-grid">
        {/* Main Control Panel */}
        <div className="chaos-main-panel">
          <ChaosLab onInject={onInject} activeMode={activeMode} />

          <div className="chaos-metrics-row">
            <MetricCard
              icon={<Clock size={16} />}
              value={`${metrics.lastLatencyMs ?? '0'}ms`}
              label="P50 Latency"
              sparkline={<Sparkline data={latencyHistory} color="#818cf8" />}
            />
            <MetricCard
              icon={<Shield size={16} />}
              value={`${sr}%`}
              label="Success Rate"
              bar={sr}
              accent={sr < 99 ? 'red' : 'green'}
              sparkline={<Sparkline data={successHistory} color={sr < 99 ? 'var(--red)' : 'var(--green)'} />}
            />
          </div>
        </div>

        {/* Lateral Observation Panel */}
        <div className="chaos-side-panel">
          <div className="panel glass-panel chaos-viz-panel">
            <div className="panel-header">
              <h2>Live Interference Mesh</h2>
              <span className="panel-tag">Real-Time Impact</span>
            </div>
            <TrafficFlow active={activeEnv?.toLowerCase()} chaosActive={status?.devops?.chaos?.active} weights={status?.devops?.canary?.weights} />
          </div>

          <div className="panel glass-panel chaos-audit-panel">
            <div className="panel-header">
              <h2>Recent Lab Activity</h2>
              <span className="panel-tag">Audit Stream</span>
            </div>
            <div className="audit-log mini-audit">
              {status.events?.slice(0, 10).map((e, idx) => (
                <div key={idx} className={`audit-entry ae-${e.level?.toLowerCase()}`}>
                  <div className="ae-icon">
                    {e.event_type?.includes('CHAOS') ? <Flame size={14} /> : <Activity size={14} />}
                  </div>
                  <div className="ae-body">
                    <div className="ae-header">
                      <span className="ae-type">{e.event_type?.replace('_', ' ')}</span>
                      <span className="ae-time">{new Date(e.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <p className="ae-msg">{e.message}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LogsView({ events }) {
  return (
    <div className="view-container animate-fade">
      <div className="terminal-panel glass-panel">
        <div className="terminal-header">
          <div className="term-dots"><span className="td red" /><span className="td yellow" /><span className="td green" /></div>
          <div className="term-title">titanium-ops-monitor.log</div>
          <div className="term-meta">CONNECTED: {new Date().toLocaleTimeString()}</div>
        </div>
        <div className="terminal-body">
          {(Array.isArray(events) ? events : []).map((e, idx) => (
            <div key={idx} className={`term-line tl-${e.level?.toLowerCase()}`}>
              <span className="tl-time">[{new Date(e.timestamp).toLocaleTimeString()}]</span>
              <span className="tl-level">{e.level}:</span>
              <span className="tl-msg">{e.message}</span>
            </div>
          ))}
          <div className="term-cursor">█</div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Components ─────────────────────────── */

function SidebarItem({ icon, label, active, onClick }) {
  return (
    <button className={`sidebar-item ${active ? 'active' : ''}`} onClick={onClick}>
      <span className="sidebar-icon">{icon}</span>
      <span className="sidebar-label">{label}</span>
      {active && <div className="sidebar-active-indicator" />}
    </button>
  );
}

function MetricCard({ icon, value, label, bar, accent, sparkline }) {
  return (
    <div className={`metric-card ${accent ? `metric-${accent}` : ''}`}>
      <div className="mc-icon">{icon}</div>
      <div className="mc-val">{value}</div>
      <div className="mc-label">{label}</div>
      {sparkline && <div className="mc-sparkline">{sparkline}</div>}
      {bar != null && (
        <div className="mbar-bg"><div className="mbar-fill" style={{ width: `${bar}%` }}></div></div>
      )}
    </div>
  );
}

function TrafficFlow({ active, chaosActive, weights }) {
  const wBlue = weights?.blue ?? 100;
  const wGreen = weights?.green ?? 0;
  // Enhanced "Titanium Mesh" Visualization
  return (
    <div className={`titanium-mesh-container ${chaosActive ? 'mesh-glitch-active' : ''}`}>
      <div className="mesh-visualization">
        <svg viewBox="0 0 400 160" className="mesh-svg">
          {/* Connection Lines */}
          <path d="M 50,80 L 150,80" className={`path-line base-line ${chaosActive ? 'line-distorted' : ''}`} />
          <path d="M 150,80 L 250,50" className={`path-line ${wBlue > 0 ? (active === 'blue' ? 'path-active-blue' : 'path-canary-blue') : 'path-dim'} ${chaosActive ? 'line-glitch' : ''}`} />
          <path d="M 150,80 L 250,110" className={`path-line ${wGreen > 0 ? (active === 'green' ? 'path-active-green' : 'path-canary-green') : 'path-dim'} ${chaosActive ? 'line-glitch' : ''}`} />

          {/* Nodes */}
          <circle cx="50" cy="80" r="6" className="mesh-node node-source" />
          <circle cx="150" cy="80" r="8" className="mesh-node node-router" />

          <g className={`target-node node-blue ${active === 'blue' ? 'active pulse-blue' : 'dim'}`}>
            <rect x="250" y="35" width="100" height="30" rx="6" className="core-box" />
            <text x="300" y="55" textAnchor="middle" className="core-label">BLUE CORE</text>
          </g>

          <g className={`target-node node-green ${active === 'green' ? 'active pulse-green' : 'dim'}`}>
            <rect x="250" y="95" width="100" height="30" rx="6" className="core-box" />
            <text x="300" y="115" textAnchor="middle" className="core-label">GREEN CORE</text>
          </g>

          {/* Chaos Interference Effect */}
          {chaosActive && (
            <g className="chaos-interference">
              <circle cx="150" cy="80" r="20" fill="none" stroke="var(--red)" strokeWidth="1" className="interfere-ring">
                <animate attributeName="r" from="15" to="40" dur="1s" repeatCount="indefinite" />
                <animate attributeName="opacity" from="0.5" to="0" dur="1s" repeatCount="indefinite" />
              </circle>
            </g>
          )}

          {/* Particle Animation (Supports Canary Split) */}
          {(wBlue > 0) && (
            <>
              <circle r="4" fill={chaosActive ? "var(--red)" : "var(--blue-bright)"} className="mesh-particle">
                <animateMotion dur={chaosActive ? "0.6s" : "1.8s"} repeatCount="indefinite" path="M 150,80 L 250,50" />
              </circle>
              {wBlue > 20 && (
                <circle r="3" fill="var(--blue-bright)" opacity="0.6">
                  <animateMotion dur="2.4s" repeatCount="indefinite" path="M 150,80 L 250,50" begin="0.8s" />
                </circle>
              )}
            </>
          )}
          {(wGreen > 0) && (
            <>
              <circle r="4" fill={chaosActive ? "var(--red)" : "var(--green-bright)"} className="mesh-particle">
                <animateMotion dur={chaosActive ? "0.6s" : "1.8s"} repeatCount="indefinite" path="M 150,80 L 250,110" />
              </circle>
              {wGreen > 20 && (
                <circle r="3" fill="var(--green-bright)" opacity="0.6">
                  <animateMotion dur="2.4s" repeatCount="indefinite" path="M 150,80 L 250,110" begin="0.8s" />
                </circle>
              )}
            </>
          )}
        </svg>
      </div>
      <div className="mesh-legend">
        <div className={`legend-item ${active === 'blue' ? 'active' : ''}`}>
          <div className="dot dot-blue" /> BLUE CHANNEL ACTIVE
        </div>
        <div className={`legend-item ${active === 'green' ? 'active' : ''}`}>
          <div className="dot dot-green" /> GREEN CHANNEL ACTIVE
        </div>
      </div>
    </div>
  );
}

function CanaryControl({ canary, onUpdate }) {
  const weights = canary.weights || { blue: 100, green: 0 };
  const [val, setVal] = useState(weights.blue);
  useEffect(() => setVal(weights.blue), [weights.blue]);

  return (
    <div className="panel glass-panel canary-panel">
      <div className="panel-header">
        <h2>Canary Control</h2>
        <span className="panel-tag">Traffic Steering</span>
      </div>
      <div className="canary-meters">
        <div className="meter-box mb-blue">
          <div className="meter-label">BLUE (STABLE)</div>
          <div className="meter-val">{val}%</div>
        </div>
        <div className="meter-box mb-green">
          <div className="meter-label">GREEN (NEXT)</div>
          <div className="meter-val">{100 - val}%</div>
        </div>
      </div>
      <div className="slider-wrapper">
        <div className="slider-labels">
          <div className="s-label-item">
            <span className="s-label-title">STABLE</span>
            <span className="s-label-sub">Production Core</span>
          </div>
          <div className="s-label-item">
            <span className="s-label-title">CANARY</span>
            <span className="s-label-sub">Experimental</span>
          </div>
        </div>
        <div className="canary-slider-field">
          <div className="canary-hint">SHIFT SLIDER TO REBALANCE</div>
          <input
            type="range" min="0" max="100" value={val}
            onChange={(e) => {
              const v = Number(e.target.value);
              setVal(v);
            }}
            onMouseUp={() => onUpdate({ blue: val, green: 100 - val })}
            className="titanium-slider-input"
          />
        </div>
      </div>
    </div>
  );
}

function ChaosLab({ onInject, activeMode }) {
  const modes = [
    {
      id: 'jitter',
      label: 'LATENCY JITTER',
      sublabel: 'Proxy Sim · 1–4s random delay',
      badge: 'SIM',
      icon: <Clock size={16} />,
      className: 'cb-latency'
    },
    {
      id: 'loss',
      label: 'PACKET LOSS',
      sublabel: 'Proxy Sim · 10% drop rate',
      badge: 'SIM',
      icon: <Activity size={16} />,
      className: 'cb-drift'
    },
    {
      id: 'error',
      label: 'CRITICAL FAIL',
      sublabel: 'Real Docker · stops active container',
      badge: 'REAL',
      icon: <ShieldAlert size={16} />,
      className: 'cb-error'
    },
    {
      id: 'blackout',
      label: 'NET BLACKOUT',
      sublabel: 'Real Docker · stops ALL containers',
      badge: 'REAL',
      icon: <X size={16} />,
      className: 'cb-blackout'
    },
  ];

  return (
    <div className="panel titanium-panel chaos-lab">
      <div className="panel-header">
        <h2>Chaos Engineering Lab</h2>
        <span className={`panel-tag ${activeMode !== 'none' ? 'danger active-blink' : ''}`}>
          {activeMode !== 'none' ? `SYSTEM UNDER ATTACK: ${activeMode.toUpperCase()}` : 'Resilience Center'}
        </span>
      </div>
      <div className="chaos-matrix">
        {modes.map(m => (
          <button
            key={m.id}
            onClick={() => onInject(m.id)}
            className={`chaos-btn ${m.className} ${activeMode === m.id ? 'active-chaos-mode' : ''}`}
          >
            <div className="cb-top">
              {m.icon}
              <span className={`cb-badge ${m.badge === 'REAL' ? 'cb-badge-real' : 'cb-badge-sim'}`}>{m.badge}</span>
            </div>
            <div className="cb-main-label">{m.label}</div>
            <div className="cb-sub-label">{m.sublabel}</div>
          </button>
        ))}
        <button onClick={() => onInject('restore')} className="chaos-btn cb-restore-all">
          <RotateCcw size={16} /> RESTORE SYSTEM
          <div className="cb-sub-label">docker start · nginx reload</div>
        </button>
      </div>
    </div>
  );
}

function Sparkline({ data, color = '#3b82f6' }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data) || 1;
  const points = data.slice(-20).map((v, i) => `${i * 10},${24 - (v / max) * 24}`).join(' ');
  return (
    <svg width="100%" height="24" viewBox="0 0 200 24" preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="2" points={points} />
    </svg>
  );
}

function ConnectivityProbe() {
  const [counts, setCounts] = useState(() => {
    const saved = sessionStorage.getItem('connectivity_counts');
    return saved ? JSON.parse(saved) : { s: 0, f: 0 };
  });

  const inFlight = React.useRef(false);

  useEffect(() => {
    const interval = setInterval(() => {
      if (inFlight.current) return;
      inFlight.current = true;
      
      fetch('/app/', { method: 'HEAD', cache: 'no-store' })
        .then(res => {
          // If we get 200, it's successful connectivity
          if (res.ok) {
            setCounts(c => ({ ...c, s: c.s + 1 }));
          } else {
            // Case out predicted chaos errors vs actual network fail
            // (Note: res.status 502/500 during chaos is a "successful" injection)
            setCounts(c => ({ ...c, f: c.f + 1 }));
          }
        })
        .catch(() => {
          setCounts(c => ({ ...c, f: c.f + 1 }));
        })
        .finally(() => {
          inFlight.current = false;
        });
    }, 400);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    sessionStorage.setItem('connectivity_counts', JSON.stringify(counts));
  }, [counts]);

  const reset = (e) => {
    e.stopPropagation();
    setCounts({ s: 0, f: 0 });
  };

  return (
    <div className="conn-probe">
      <div className="probe-head">
        <div className="probe-dot" /> LIVE PROBE
      </div>
      <div className="probe-stats">
        <span className="p-ok">OK: {counts.s}</span>
        <span className="p-err">FAIL: {counts.f}</span>
      </div>
      <button className="probe-reset" onClick={reset} title="Reset Counters">
        <RotateCcw size={10} />
      </button>
    </div>
  );
}
