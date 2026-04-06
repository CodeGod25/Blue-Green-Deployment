const { useEffect, useMemo, useState } = React;

const SOURCE_STYLES = {
  manual: "tag-manual",
  demo: "tag-demo",
  promote: "tag-promote",
  "auto-rollback": "tag-rollback",
  initial: "tag-initial",
};

const SOURCES = ["all", "manual", "demo", "promote", "auto-rollback"];

function toTitle(value) {
  if (!value) {
    return "Unknown";
  }
  return String(value)
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function formatClock(value) {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "--";
  }
  return parsed.toLocaleTimeString();
}

function formatAgo(value) {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  const deltaSeconds = Math.floor((Date.now() - parsed.getTime()) / 1000);
  if (Number.isNaN(deltaSeconds)) {
    return "--";
  }
  if (deltaSeconds < 5) {
    return "just now";
  }
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  const minutes = Math.floor(deltaSeconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

function formatPercent(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

async function copyText(text) {
  if (!text) {
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch (_error) {
  }

  const helper = document.createElement("textarea");
  helper.value = text;
  helper.style.position = "fixed";
  helper.style.left = "-9999px";
  document.body.appendChild(helper);
  helper.select();
  document.execCommand("copy");
  helper.remove();
}

function useLiveStatus() {
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  useEffect(() => {
    let closed = false;
    let stream = null;

    const applyStatus = (payload) => {
      if (closed || !payload) {
        return;
      }
      setStatus(payload);
      setLastUpdatedAt(new Date().toISOString());
    };

    const fetchSnapshot = async () => {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) {
          throw new Error("status fetch failed");
        }
        const payload = await response.json();
        applyStatus(payload);
      } catch (_error) {
      }
    };

    const connect = () => {
      stream = new EventSource("/api/events/stream");

      stream.addEventListener("status", (event) => {
        try {
          applyStatus(JSON.parse(event.data));
          setConnected(true);
        } catch (_error) {
          setConnected(false);
        }
      });

      stream.onerror = () => {
        setConnected(false);
      };
    };

    fetchSnapshot();
    connect();

    const fallbackPoll = setInterval(() => {
      if (!connected) {
        fetchSnapshot();
      }
    }, 3000);

    return () => {
      closed = true;
      clearInterval(fallbackPoll);
      if (stream) {
        stream.close();
      }
    };
  }, [connected]);

  return { status, connected, lastUpdatedAt };
}

function HealthPill({ healthy }) {
  return (
    <span className={`health-pill ${healthy ? "healthy" : "unhealthy"}`}>
      {healthy ? "Healthy" : "Unavailable"}
    </span>
  );
}

function CommandBlock({ title, command, subtitle }) {
  return (
    <div className="cmd-block">
      <div className="cmd-title-row">
        <div>
          <div className="cmd-title">{title}</div>
          {subtitle ? <div className="cmd-subtitle">{subtitle}</div> : null}
        </div>
      </div>
      <pre>{command}</pre>
      <button className="btn-secondary" onClick={() => copyText(command)}>
        Copy
      </button>
    </div>
  );
}

function Stage({ label, passed, detail }) {
  return (
    <article className={`stage ${passed ? "pass" : "fail"}`}>
      <header>
        <strong>{label}</strong>
        <span>{passed ? "PASS" : "FAIL"}</span>
      </header>
      <p>{detail}</p>
    </article>
  );
}

function App() {
  const { status, connected, lastUpdatedAt } = useLiveStatus();
  const [eventFilter, setEventFilter] = useState("all");
  const [targetOverride, setTargetOverride] = useState("");
  const [profileOverride, setProfileOverride] = useState("");

  const active = status?.active || {};
  const metrics = status?.metrics || {};
  const services = status?.services || {};
  const events = status?.events || [];
  const profilesContainer = status?.profiles || {};
  const profiles = profilesContainer.profiles || {};
  const devops = status?.devops || {};
  const history = status?.history?.last60s || [];

  const release = status?.releaseManifest || {};
  const defaultProfile = profilesContainer.defaultProfile || "learnhub-local";
  const selectedProfile = profileOverride || active.profile || defaultProfile;
  const selectedTarget = targetOverride || devops.nextTarget || "green";

  useEffect(() => {
    if (!targetOverride && devops.nextTarget) {
      setTargetOverride(devops.nextTarget);
    }
  }, [targetOverride, devops.nextTarget]);

  useEffect(() => {
    if (!profileOverride && active.profile) {
      setProfileOverride(active.profile);
    }
  }, [profileOverride, active.profile]);

  const profileEntries = useMemo(() => Object.entries(profiles), [profiles]);

  const filteredEvents = useMemo(() => {
    const rows = [...events].reverse();
    if (eventFilter === "all") {
      return rows;
    }
    return rows.filter((event) => event.source === eventFilter);
  }, [events, eventFilter]);

  const blueCount = Number(metrics?.versionCounts?.Blue || 0);
  const greenCount = Number(metrics?.versionCounts?.Green || 0);
  const totalCount = Math.max(1, blueCount + greenCount);
  const ratio = Math.round((blueCount / totalCount) * 100);

  const commands = {
    shellSwitch: `./switch_traffic.sh ${selectedTarget} --profile ${selectedProfile}`,
    shellPromote: `./promote_release.sh ${selectedTarget} --profile ${selectedProfile} --checks 3 --interval 2`,
    psSwitch: `./switch_traffic.ps1 -Target ${selectedTarget} -Profile ${selectedProfile}`,
    psPromote: `./promote_release.ps1 -Target ${selectedTarget} -DeployKey ${selectedProfile} -Checks 3 -IntervalSeconds 2`,
  };

  const profileDescription = profiles[selectedProfile]?.description || devops.activeProfileDescription || "";

  const headline = useMemo(() => {
    if (!status) {
      return "Collecting live release telemetry...";
    }

    if (devops.preflightReady) {
      return `System is healthy. You can promote ${toTitle(devops.nextTarget)} confidently.`;
    }

    return `Promotion is blocked. Resolve failing checks before switching traffic.`;
  }, [status, devops]);

  const runbookSteps = useMemo(() => {
    const checks = Array.isArray(devops.checks) ? devops.checks : [];
    const failedChecks = checks.filter((check) => !check.passed);

    if (devops.preflightReady) {
      return [
        `1. Validate target '${selectedTarget}' readiness in the health map.`,
        "2. Run promotion command with checks.",
        "3. Watch the Event Timeline and Live Trace for 30-60 seconds.",
      ];
    }

    if (failedChecks.length === 0) {
      return ["Collect more telemetry from the live trace before promoting."];
    }

    return failedChecks.map((check, index) => `${index + 1}. Fix ${check.name}: ${check.detail}`);
  }, [devops, selectedTarget]);

  const primaryCommand = devops.preflightReady ? commands.psPromote : commands.psSwitch;
  const fullRunbookText = `${commands.psSwitch}\n${commands.psPromote}`;

  const liveWindow = status?.history?.last60s || [];
  const latestLatencyPoints = liveWindow.slice(-30);

  const serviceRows = [
    { key: "proxy", title: "Ingress Proxy" },
    { key: "blue", title: "Blue Environment" },
    { key: "green", title: "Green Environment" },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-dot" />
          <div>
            <p>LearnHub Ops</p>
            <strong>Release Intelligence Hub</strong>
          </div>
        </div>

        <div className="sidebar-block">
          <p className="sidebar-label">Environment</p>
          <h2>{toTitle(active.target)}</h2>
          <p>{active.upstream || "--"}</p>
        </div>

        <div className="sidebar-block">
          <p className="sidebar-label">Profile</p>
          <h3>{selectedProfile}</h3>
          <p>{profileDescription || "No description available"}</p>
        </div>

        <div className="sidebar-block">
          <p className="sidebar-label">Release</p>
          <h3>{release.release || "Not published"}</h3>
          <p>{release.notes || "Release metadata unavailable."}</p>
        </div>

        <div className="sidebar-block">
          <p className="sidebar-label">Live State</p>
          <span className={`stream-status ${connected ? "live" : "offline"}`}>
            {connected ? "Connected" : "Reconnecting"}
          </span>
          <p>Updated {formatAgo(lastUpdatedAt)}</p>
          <p>Last switch {formatClock(active.changedAt)}</p>
        </div>
      </aside>

      <main className="main">
        <header className="hero">
          <div>
            <p className="eyebrow">Blue-Green Command Center</p>
            <h1>{headline}</h1>
            <p className="subtext">
              This view turns telemetry into decisions: what is running, what is safe to promote, and exactly which commands to execute next.
            </p>
          </div>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => copyText(primaryCommand)}>Copy Primary Command</button>
            <button className="btn-secondary" onClick={() => copyText(fullRunbookText)}>Copy Full Runbook</button>
          </div>
        </header>

        <section className="kpi-grid">
          <article className="kpi-card">
            <p>Requests / sec</p>
            <strong>{Number(metrics.rps || 0).toFixed(2)}</strong>
            <span>Live proxy sampling</span>
          </article>

          <article className="kpi-card">
            <p>Success rate</p>
            <strong>{formatPercent(metrics.successRate)}</strong>
            <span>Error rate {formatPercent(metrics.errorRate)}</span>
          </article>

          <article className="kpi-card">
            <p>Latency / status</p>
            <strong>{Number(metrics.lastLatencyMs || 0).toFixed(2)} ms</strong>
            <span>HTTP {metrics.lastStatusCode || "--"}</span>
          </article>

          <article className="kpi-card">
            <p>Checks observed</p>
            <strong>{formatNumber(metrics.totalRequests || 0)}</strong>
            <span>Version stream: {metrics.currentVersion || "Unknown"}</span>
          </article>
        </section>

        <section className="content-grid">
          <section className="panel panel-wide">
            <div className="panel-head">
              <h2>Decision Center</h2>
              <span className={`gate ${devops.preflightReady ? "ready" : "blocked"}`}>
                {devops.preflightReady ? "Ready To Promote" : "Promotion Blocked"}
              </span>
            </div>

            <div className="stage-grid">
              {(devops.checks || []).map((check) => (
                <Stage
                  key={check.name}
                  label={check.name}
                  passed={Boolean(check.passed)}
                  detail={check.detail || "No detail"}
                />
              ))}
            </div>

            <ol className="runbook-list">
              {runbookSteps.map((step, index) => (
                <li key={`${index}-${step}`}>{step}</li>
              ))}
            </ol>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Service Health</h2>
              <span className="muted">Profile {selectedProfile}</span>
            </div>

            <div className="service-grid">
              {serviceRows.map((service) => {
                const row = services[service.key] || {};
                return (
                  <article className="service-card" key={service.key}>
                    <div className="service-top">
                      <h3>{service.title}</h3>
                      <HealthPill healthy={Boolean(row.healthy)} />
                    </div>
                    <p className="service-url">{row.url || "No endpoint"}</p>
                    <div className="service-meta">
                      <span>Code {row.statusCode || 0}</span>
                      <span>{Number(row.latencyMs || 0).toFixed(2)} ms</span>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Release Manifest</h2>
              <span className="muted">Active via proxy</span>
            </div>

            <dl className="manifest-grid">
              <div>
                <dt>Release</dt>
                <dd>{release.release || "--"}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{release.version || "--"}</dd>
              </div>
              <div>
                <dt>Track</dt>
                <dd>{release.track || "--"}</dd>
              </div>
              <div>
                <dt>Build</dt>
                <dd>{release.build || "--"}</dd>
              </div>
            </dl>
            <p className="summary-text">{release.notes || "No release notes available."}</p>
          </section>

          <section className="panel panel-wide">
            <div className="panel-head">
              <h2>Command Studio</h2>
              <span className="muted">Generate actions by profile and target</span>
            </div>

            <div className="builder-grid">
              <label>
                Profile
                <select value={selectedProfile} onChange={(event) => setProfileOverride(event.target.value)}>
                  {Object.keys(profiles).map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>

              <label>
                Target
                <select value={selectedTarget} onChange={(event) => setTargetOverride(event.target.value)}>
                  <option value="blue">Blue</option>
                  <option value="green">Green</option>
                </select>
              </label>
            </div>

            {profileDescription ? <p className="summary-text">{profileDescription}</p> : null}

            <div className="cmd-grid">
              <CommandBlock
                title="PowerShell Switch"
                subtitle="Fast traffic move"
                command={commands.psSwitch}
              />
              <CommandBlock
                title="Shell Switch"
                subtitle="Fast traffic move"
                command={commands.shellSwitch}
              />
              <CommandBlock
                title="PowerShell Promote"
                subtitle="Preflight + postflight checks"
                command={commands.psPromote}
              />
              <CommandBlock
                title="Shell Promote"
                subtitle="Preflight + postflight checks"
                command={commands.shellPromote}
              />
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Live Latency Pulse</h2>
              <span className="muted">Last 30 points</span>
            </div>

            <div className="spark-wrap">
              {(latestLatencyPoints.length ? latestLatencyPoints : [{ code: 0, latencyMs: 0 }]).map((point, index) => {
                const code = Number(point.code || 0);
                const latency = Number(point.latencyMs || 0);
                const height = Math.max(16, Math.min(96, latency * 1.2 + 10));
                return (
                  <div
                    key={`${index}-${point.ts || index}`}
                    className={`spark-bar ${code === 200 ? "ok" : "bad"}`}
                    style={{ height: `${height}%` }}
                    title={`code ${code} | ${latency.toFixed(2)} ms`}
                  />
                );
              })}
            </div>

            <p className="muted">Recent errors in 60s: {status?.history?.recentErrorCount || 0}</p>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Event Timeline</h2>
              <select value={eventFilter} onChange={(event) => setEventFilter(event.target.value)} className="compact-select">
                {SOURCES.map((source) => (
                  <option key={source} value={source}>{source === "all" ? "All sources" : toTitle(source)}</option>
                ))}
              </select>
            </div>

            <ul className="event-list">
              {filteredEvents.length === 0 ? (
                <li className="event-empty">No events for this filter yet.</li>
              ) : (
                filteredEvents.slice(0, 14).map((event, index) => (
                  <li key={`${event.timestamp}-${index}`}>
                    <div>
                      <span className={`tag ${SOURCE_STYLES[event.source] || "tag-default"}`}>
                        {toTitle(event.source)}
                      </span>
                      <strong>{toTitle(event.event)} to {toTitle(event.target)}</strong>
                      <p>{event.profile}{" -> "}{event.upstream}</p>
                    </div>
                    <time>{formatClock(event.timestamp)}</time>
                  </li>
                ))
              )}
            </ul>
          </section>

          <section className="panel panel-wide">
            <div className="panel-head">
              <h2>Profile Catalog</h2>
              <span className="muted">Integration contexts</span>
            </div>

            <div className="profile-table">
              <div className="profile-row profile-head-row">
                <span>Name</span>
                <span>Blue Upstream</span>
                <span>Green Upstream</span>
                <span>Status</span>
              </div>

              {Object.entries(profiles).map(([name, profile]) => {
                const isActive = name === selectedProfile;
                return (
                  <div className="profile-row" key={name}>
                    <span>
                      <strong>{name}</strong>
                      {profile.description ? <em>{profile.description}</em> : null}
                    </span>
                    <span>{profile.blue || "--"}</span>
                    <span>{profile.green || "--"}</span>
                    <span>
                      {isActive ? (
                        <span className="profile-active">Active</span>
                      ) : (
                        <button className="btn-secondary" onClick={() => setProfileOverride(name)}>
                          Use Profile
                        </button>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        </section>
      </main>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
