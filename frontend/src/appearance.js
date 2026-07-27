const STORAGE_KEY = 'birb_appearance';
const DEFAULTS = { mode: 'light', accent: '#B35610' };

export function readAppearance() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}

export function applyAppearance(settings = readAppearance()) {
  const systemDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const resolvedMode = settings.mode === 'system'
    ? (systemDark ? 'dark' : 'light')
    : settings.mode;
  document.documentElement.dataset.theme = resolvedMode;
  document.documentElement.style.setProperty('--accent', settings.accent);
  return settings;
}

export function saveAppearance(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  applyAppearance(settings);
}

applyAppearance();

window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
  const settings = readAppearance();
  if (settings.mode === 'system') applyAppearance(settings);
});
