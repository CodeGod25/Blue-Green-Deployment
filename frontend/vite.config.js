import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Mock API plugin — simulates the backend so you can view the dashboard without Docker
function mockApiPlugin() {
  let activeTarget = 'blue';
  let totalRequests = 1847;
  let successRequests = 1847;
  let lastDeploymentId = null;

  const generateDeploymentId = () => {
    return 'dep-' + Math.random().toString(36).substring(2, 10) + '-' + Date.now().toString(36);
  };

  return {
    name: 'mock-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/api/status') {
          totalRequests += Math.floor(Math.random() * 3) + 1;
          successRequests = totalRequests;
          const successRate = totalRequests > 0 ? 100.0 : 0;

          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.end(JSON.stringify({
            timestamp: new Date().toISOString(),
            monitoredUrl: 'http://proxy/',
            active: {
              profile: 'learnhub-local',
              target: activeTarget,
              upstream: `${activeTarget}:80`,
              changedAt: new Date(Date.now() - 120000).toISOString(),
              source: 'api',
            },
            metrics: {
              totalRequests,
              successRequests,
              failedRequests: 0,
              successRate,
              errorRate: 0,
              rps: (Math.random() * 2 + 1.5).toFixed(2),
              lastStatusCode: 200,
              lastLatencyMs: (Math.random() * 10 + 4).toFixed(2),
              currentVersion: activeTarget.charAt(0).toUpperCase() + activeTarget.slice(1),
              versionCounts: { Blue: activeTarget === 'blue' ? totalRequests : 0, Green: activeTarget === 'green' ? totalRequests : 0, Unknown: 0 },
            },
            services: {
              proxy: { url: 'http://proxy/', healthy: true, statusCode: 200, latencyMs: 5.2 },
              blue: { url: 'http://blue:80/healthz', healthy: true, statusCode: 200, latencyMs: 3.1 },
              green: { url: 'http://green:80/healthz', healthy: true, statusCode: 200, latencyMs: 3.8 },
            },
            devops: {
              nextTarget: activeTarget === 'blue' ? 'green' : 'blue',
              preflightReady: true,
              checks: [
                { name: 'Proxy health', passed: true, detail: 'Proxy is healthy' },
                { name: `${activeTarget === 'blue' ? 'Green' : 'Blue'} health`, passed: true, detail: 'Endpoint reachable' },
                { name: 'Error budget', passed: true, detail: 'Error rate is 0%' },
              ],
              summary: 'System is healthy and ready for the next promotion.',
            },
            events: [
              { timestamp: new Date(Date.now() - 2000).toISOString(), level: 'INFO', eventType: 'PROBE_SUCCESS', message: `Health check passed: ${activeTarget} environment`, deploymentId: lastDeploymentId },
              { timestamp: new Date(Date.now() - 5000).toISOString(), level: 'INFO', eventType: 'DEPLOY_SUCCESS', message: `Traffic switched to ${activeTarget}`, deploymentId: lastDeploymentId },
              { timestamp: new Date(Date.now() - 8000).toISOString(), level: 'INFO', eventType: 'CONFIG_UPDATED', message: `Nginx upstream configuration updated to ${activeTarget}:80`, deploymentId: lastDeploymentId },
              { timestamp: new Date(Date.now() - 15000).toISOString(), level: 'INFO', eventType: 'DEPLOY_START', message: `Deployment to ${activeTarget} initiated`, deploymentId: lastDeploymentId },
              { timestamp: new Date(Date.now() - 25000).toISOString(), level: 'INFO', eventType: 'PREFLIGHT_CHECK', message: 'Pre-deployment checks completed successfully' },
              { timestamp: new Date(Date.now() - 35000).toISOString(), level: 'INFO', eventType: 'PROBE_SUCCESS', message: `Health check passed: ${activeTarget === 'blue' ? 'green' : 'blue'} environment` },
              { timestamp: new Date(Date.now() - 60000).toISOString(), level: 'INFO', eventType: 'PROBE_SUCCESS', message: 'All services healthy' },
              { timestamp: new Date(Date.now() - 90000).toISOString(), level: 'INFO', eventType: 'SYSTEM_STATUS', message: 'Monitoring system initialized' },
              { timestamp: new Date(Date.now() - 120000).toISOString(), level: 'INFO', eventType: 'DEPLOY_SUCCESS', message: `Previous deployment to ${activeTarget}` },
              { timestamp: new Date(Date.now() - 150000).toISOString(), level: 'INFO', eventType: 'SYSTEM_READY', message: 'All components operational' },
            ],
          }));
          return;
        }

        if (req.url === '/api/deploy' && req.method === 'POST') {
          let body = '';
          req.on('data', chunk => { body += chunk; });
          req.on('end', () => {
            try {
              const { target } = JSON.parse(body);
              if (target === 'blue' || target === 'green') {
                activeTarget = target;
                lastDeploymentId = generateDeploymentId();
                res.setHeader('Content-Type', 'application/json');
                res.end(JSON.stringify({
                  status: 'success',
                  message: `Switched to ${target}`,
                  timestamp: new Date().toISOString(),
                  deploymentId: lastDeploymentId,
                  steps: [
                    { id: 'preflight', label: 'Preflight checks', status: 'completed' },
                    { id: 'config', label: 'Updating upstream config', status: 'completed' },
                    { id: 'nginx', label: 'Reloading Nginx', status: 'completed' },
                    { id: 'health', label: 'Health check', status: 'completed' },
                    { id: 'done', label: 'Switch complete', status: 'completed' },
                  ],
                }));
              } else {
                res.writeHead(400);
                res.end(JSON.stringify({ error: 'Invalid target' }));
              }
            } catch {
              res.writeHead(400);
              res.end(JSON.stringify({ error: 'Bad request' }));
            }
          });
          return;
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), mockApiPlugin()],
  base: '/',
  build: {
    outDir: 'dist',
  }
})

