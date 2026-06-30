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
  const { subscribe, set } = writable(initial);

  return {
    subscribe,
    login(user, token) {
      _current = { user, token };
      _persist(_current);
      set(_current);
    },
    updateUser(updates) {
      if (!_current) return;
      _current = { ..._current, user: { ..._current.user, ...updates } };
      _persist(_current);
      set(_current);
    },
    logout() {
      _current = null;
      try { localStorage.removeItem(STORAGE_KEY); } catch (err) {
        console.warn('Could not clear auth from localStorage:', err);
      }
      set(null);
    },
  };
}

export const auth = createAuthStore();
