/**
 * Egeria Advisor — Auth module
 *
 * Manages JWT-based authentication state in sessionStorage.
 * Handles standalone login, portal SSO (postMessage + URL fragment), and logout.
 *
 * Usage:
 *   Auth.getHeaders()          — object with Authorization header for fetch calls
 *   Auth.isAuthenticated()     — boolean
 *   Auth.showLogin()           — programmatically show the login overlay
 *   Auth.init(onReady)         — call on DOMContentLoaded; fires onReady() when done
 */
const Auth = (() => {
  const TOKEN_KEY = 'ea_token';

  // ── Token helpers ────────────────────────────────────────────────────────

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
  }

  function isAuthenticated() {
    const token = getToken();
    if (!token) return false;
    try {
      // Decode the JWT payload (no signature verification — server handles that)
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp > Math.floor(Date.now() / 1000);
    } catch {
      return false;
    }
  }

  function getUser() {
    const token = getToken();
    if (!token) return null;
    try {
      return JSON.parse(atob(token.split('.')[1]));
    } catch {
      return null;
    }
  }

  function getHeaders() {
    const token = getToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  }

  // ── UI helpers ───────────────────────────────────────────────────────────

  function showLogin(message) {
    const overlay = document.getElementById('login-overlay');
    if (!overlay) return;
    if (message) {
      const msg = document.getElementById('login-message');
      if (msg) { msg.textContent = message; msg.classList.remove('hidden'); }
    }
    overlay.classList.remove('hidden');
    setTimeout(() => document.getElementById('login-username')?.focus(), 50);
  }

  function hideLogin() {
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.classList.add('hidden');
    const msg = document.getElementById('login-message');
    if (msg) msg.classList.add('hidden');
    const err = document.getElementById('login-error');
    if (err) { err.textContent = ''; err.classList.add('hidden'); }
    // Show the "Sign in" button in the header so user can get back to login
    const signinBtn = document.getElementById('login-header-btn');
    if (signinBtn && !isAuthenticated()) signinBtn.classList.remove('hidden');
  }

  function updateUserDisplay() {
    const el = document.getElementById('current-user');
    if (!el) return;
    const user = getUser();
    const signinBtn = document.getElementById('login-header-btn');
    if (user) {
      el.textContent = user.egeria_user || user.sub || '';
      el.classList.remove('hidden');
      document.getElementById('logout-btn')?.classList.remove('hidden');
      if (signinBtn) signinBtn.classList.add('hidden');
    } else {
      el.textContent = '';
      el.classList.add('hidden');
      document.getElementById('logout-btn')?.classList.add('hidden');
    }
  }

  function setLoginLoading(loading) {
    const btn = document.getElementById('login-submit-btn');
    if (!btn) return;
    btn.disabled = loading;
    btn.textContent = loading ? 'Signing in…' : 'Sign in';
  }

  // ── Login flow ───────────────────────────────────────────────────────────

  async function doLogin() {
    const username = document.getElementById('login-username')?.value.trim();
    const password = document.getElementById('login-password')?.value;
    const errEl    = document.getElementById('login-error');

    if (!username || !password) {
      if (errEl) { errEl.textContent = 'Please enter username and password.'; errEl.classList.remove('hidden'); }
      return;
    }

    setLoginLoading(true);
    if (errEl) errEl.classList.add('hidden');

    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await r.json();
      if (!r.ok) {
        const msg = data.detail || 'Login failed.';
        if (errEl) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
        return;
      }
      setToken(data.access_token);
      hideLogin();
      updateUserDisplay();
      // Signal the app that auth succeeded
      document.dispatchEvent(new CustomEvent('ea:authenticated', { detail: { user: data.egeria_user } }));
    } catch (e) {
      if (errEl) { errEl.textContent = `Connection error: ${e.message}`; errEl.classList.remove('hidden'); }
    } finally {
      setLoginLoading(false);
    }
  }

  function doLogout() {
    clearToken();
    updateUserDisplay();
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
    showLogin();
  }

  // ── Portal SSO ───────────────────────────────────────────────────────────

  async function exchangePortalToken(portalToken) {
    try {
      const r = await fetch('/api/auth/portal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ portal_token: portalToken }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      setToken(data.access_token);
      updateUserDisplay();
      document.dispatchEvent(new CustomEvent('ea:authenticated', { detail: { user: data.egeria_user } }));
      return true;
    } catch {
      return false;
    }
  }

  function listenForPortalMessage() {
    window.addEventListener('message', async (event) => {
      // Only accept messages from configured portal origins
      const allowed = ['http://localhost:8885', window.location.origin];
      if (!allowed.includes(event.origin)) return;
      if (event.data?.type !== 'egeria_auth' || !event.data?.portal_token) return;
      await exchangePortalToken(event.data.portal_token);
    });
  }

  async function checkUrlFragment() {
    const hash = window.location.hash;
    if (!hash.startsWith('#pt=')) return false;
    const portalToken = hash.slice(4);
    // Clear the fragment immediately so credentials don't stay in the URL bar
    history.replaceState(null, '', window.location.pathname + window.location.search);
    return await exchangePortalToken(portalToken);
  }

  // ── Handle 401 responses ─────────────────────────────────────────────────

  function handle401() {
    clearToken();
    updateUserDisplay();
    showLogin('Your session has expired. Please sign in again.');
  }

  // ── Init ─────────────────────────────────────────────────────────────────

  async function init(onReady) {
    // Wire up login form submit
    document.getElementById('login-submit-btn')?.addEventListener('click', doLogin);
    document.getElementById('login-password')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') doLogin();
    });
    document.getElementById('login-username')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') document.getElementById('login-password')?.focus();
    });

    // Wire up logout button
    document.getElementById('logout-btn')?.addEventListener('click', doLogout);

    // After login, refresh Egeria-dependent sidebar sections
    document.addEventListener('ea:authenticated', () => {
      updateUserDisplay();
      if (typeof loadReports === 'function') loadReports();
      if (typeof loadPlans   === 'function') loadPlans();
      if (typeof loadDrafts  === 'function') loadDrafts();
    });

    // Start portal SSO listener
    listenForPortalMessage();

    // Check URL fragment first (portal opened in new tab)
    const fromPortal = await checkUrlFragment();

    // Already have a valid token (or just got one from portal)
    if (isAuthenticated()) {
      updateUserDisplay();
      onReady && onReady();
      return;
    }

    // No valid token — start the app anyway (anonymous RAG mode), but show login overlay.
    // The login overlay is dismissible so users can access knowledge features immediately.
    onReady && onReady();
    showLogin();
  }

  return { init, isAuthenticated, getToken, getHeaders, getUser, showLogin, hideLogin, doLogout, handle401, updateUserDisplay };
})();
