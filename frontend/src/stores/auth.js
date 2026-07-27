import { writable } from 'svelte/store';

const STORAGE_KEY = 'birb_auth';

function _persist(state) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (err) {
    console.warn('Could not persist auth to localStorage:', err);
  }
}

function createAuthStore() {
  let initial = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) initial = JSON.parse(raw);
  } catch (err) {
    console.warn('Could not read auth from localStorage:', err);
  }

  let _current = initial;
  let expiryTimer = null;
  const { subscribe, set } = writable(initial);

  function logout() {
    _current = null;
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = null;
    try { localStorage.removeItem(STORAGE_KEY); } catch (err) {
      console.warn('Could not clear auth from localStorage:', err);
    }
    set(null);
  }

  function scheduleExpiry(state) {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = null;
    const token = state?.token;
    if (!token) return;
    try {
      const encoded = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=');
      const payload = JSON.parse(atob(padded));
      const remaining = (payload.exp * 1000) - Date.now();
      if (remaining <= 0) {
        logout();
      } else {
        // Browsers cap timeouts at roughly 24.8 days.
        expiryTimer = setTimeout(
          () => scheduleExpiry(_current),
          Math.min(remaining, 2_147_000_000),
        );
      }
    } catch {
      logout();
    }
  }

  const store = {
    subscribe,
    login(user, token) {
      _current = { user, token };
      _persist(_current);
      set(_current);
      scheduleExpiry(_current);
    },
    updateUser(updates) {
      if (!_current) return;
      _current = { ..._current, user: { ..._current.user, ...updates } };
      _persist(_current);
      set(_current);
    },
    logout,
  };

  scheduleExpiry(initial);
  return store;
}

export const auth = createAuthStore();
