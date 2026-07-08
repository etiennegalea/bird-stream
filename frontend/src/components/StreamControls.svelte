<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/StreamControls.css';

  let videoEnabled = true;
  let audioEnabled = true;
  let loading = true;
  let saving = false;
  let error = '';

  function authHeader() {
    const token = get(auth)?.token;
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  async function fetchSettings() {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream-settings`, { headers: authHeader() });
      if (resp.ok) {
        const data = await resp.json();
        videoEnabled = data.video_enabled;
        audioEnabled = data.audio_enabled;
        error = '';
      } else {
        error = resp.status === 403 ? 'Admin access required' : 'Failed to load settings';
      }
    } catch {
      error = 'Network error';
    } finally {
      loading = false;
    }
  }

  async function updateSetting(patch) {
    saving = true;
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream-settings`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify(patch),
      });
      if (resp.ok) {
        const data = await resp.json();
        videoEnabled = data.video_enabled;
        audioEnabled = data.audio_enabled;
        error = '';
      } else {
        error = resp.status === 403 ? 'Admin access required' : 'Failed to update settings';
      }
    } catch {
      error = 'Network error';
    } finally {
      saving = false;
    }
  }

  onMount(fetchSettings);
</script>

<div class="stream-controls" role="dialog" aria-label="Stream controls">
  <div class="stream-controls-title">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
    </svg>
    STREAM CONTROLS
  </div>

  {#if loading}
    <p class="stream-controls-status">Loading…</p>
  {:else}
    <label class="stream-controls-row">
      <span class="stream-controls-label">
        Video stream
        <span class="stream-controls-state" class:off={!videoEnabled}>
          {videoEnabled ? 'LIVE' : 'BLOCKED'}
        </span>
      </span>
      <input
        type="checkbox"
        class="stream-toggle"
        checked={videoEnabled}
        disabled={saving}
        on:change={(e) => updateSetting({ video_enabled: e.target.checked })}
        aria-label="Toggle video stream"
      />
    </label>

    <label class="stream-controls-row">
      <span class="stream-controls-label">
        Audio stream
        <span class="stream-controls-state" class:off={!audioEnabled}>
          {audioEnabled ? 'LIVE' : 'BLOCKED'}
        </span>
      </span>
      <input
        type="checkbox"
        class="stream-toggle"
        checked={audioEnabled}
        disabled={saving}
        on:change={(e) => updateSetting({ audio_enabled: e.target.checked })}
        aria-label="Toggle audio stream"
      />
    </label>

    {#if error}
      <p class="stream-controls-error">{error}</p>
    {/if}
  {/if}
</div>
