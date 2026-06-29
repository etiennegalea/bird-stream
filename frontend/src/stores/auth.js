import { writable } from 'svelte/store';

const STORAGE_KEY = 'birb_auth';

function createAuthStore() {
  let initial = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) initial = JSON.parse(raw);
  } catch (err) {
    console.warn('Could not read auth from localStorage:', err);
  }

  const { subscribe, set } = writable(initial);

  return {
    subscribe,
    login(user, token) {
      const state = { user, token };
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (err) {
        console.warn('Could not persist auth to localStorage:', err);
      }
      set(state);
    },
    logout() {
      try { localStorage.removeItem(STORAGE_KEY); } catch (err) {
        console.warn('Could not clear auth from localStorage:', err);
      }
      set(null);
    },
  };
}

export const auth = createAuthStore();
