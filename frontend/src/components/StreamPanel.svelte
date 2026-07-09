<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/StreamPanel.css';

  const dispatch = createEventDispatcher();

  // ── Broadcast settings (public video/audio blocking) ────────────────────
  let videoEnabled = true;
  let audioEnabled = false; // matches server default: audio is opt-in
  let settingsLoading = true;
  let saving = false;
  let settingsError = '';

  // ── Transmitter devices (via backend MQTT bridge) ───────────────────────
  let devices = [];
  let brokerConnected = false;
  let devicesLoading = true;
  let devicesError = '';
  let pending = {};       // pi_id -> true while a command is in flight
  let schedPending = {};  // pi_id -> true while a schedule save is in flight
  let scheduleForms = {}; // pi_id -> { enabled, start, end } (edit buffer)
  let pollTimer = null;

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
        settingsError = '';
      } else {
        settingsError = resp.status === 403 ? 'Admin access required' : 'Failed to load settings';
      }
    } catch {
      settingsError = 'Network error';
    } finally {
      settingsLoading = false;
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
        settingsError = '';
      } else {
        settingsError = resp.status === 403 ? 'Admin access required' : 'Failed to update settings';
      }
    } catch {
      settingsError = 'Network error';
    } finally {
      saving = false;
    }
  }

  async function fetchDevices() {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream/devices`, { headers: authHeader() });
      if (resp.ok) {
        const data = await resp.json();
        brokerConnected = data.broker_connected;
        devices = data.devices;
        // Seed each device's schedule edit-buffer once, from its reported
        // window; don't clobber a form the admin may be editing.
        for (const d of devices) {
          if (!scheduleForms[d.pi_id]) {
            const s = d.schedule || {};
            scheduleForms[d.pi_id] = {
              enabled: !!s.enabled,
              start: s.start || '06:00',
              end: s.end || '20:00',
            };
          }
        }
        scheduleForms = scheduleForms;
        devicesError = '';
      } else {
        devicesError = resp.status === 403 ? 'Admin access required' : 'Failed to load devices';
      }
    } catch {
      devicesError = 'Network error';
    } finally {
      devicesLoading = false;
    }
  }

  async function sendCommand(piId, action) {
    pending = { ...pending, [piId]: true };
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream/devices/${piId}/${action}`, {
        method: 'POST',
        headers: authHeader(),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        devicesError = body.detail || `Failed to send '${action}'`;
      } else {
        devicesError = '';
      }
    } catch {
      devicesError = 'Network error';
    }
    // The Pi confirms over MQTT within a second or two — refresh shortly.
    setTimeout(async () => {
      await fetchDevices();
      pending = { ...pending, [piId]: false };
    }, 1500);
  }

  async function saveSchedule(piId) {
    const form = scheduleForms[piId];
    if (!form) return;
    schedPending = { ...schedPending, [piId]: true };
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream/devices/${piId}/schedule`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({ enabled: form.enabled, start: form.start, end: form.end }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        devicesError = body.detail || 'Failed to save schedule';
      } else {
        devicesError = '';
      }
    } catch {
      devicesError = 'Network error';
    }
    // The Pi applies + reports back over MQTT within a second or two.
    setTimeout(async () => {
      await fetchDevices();
      schedPending = { ...schedPending, [piId]: false };
    }, 1500);
  }

  function statusOf(d) {
    if (d.stale && d.status !== 'offline') return 'unreachable';
    if (d.status === 'idle' && d.resting) return 'resting';
    return d.status || 'unknown';
  }

  onMount(() => {
    fetchSettings();
    fetchDevices();
    pollTimer = setInterval(fetchDevices, 5000);
  });
  onDestroy(() => clearInterval(pollTimer));
</script>

<div class="stream-drawer" role="region" aria-label="Stream control panel">
  <div class="stream-drawer-header">
    <div class="stream-drawer-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
      </svg>
      STREAM
    </div>
    <button class="stream-close-btn" on:click={() => dispatch('close')} aria-label="Close stream panel">✕</button>
  </div>

  <div class="stream-drawer-body">
    <!-- Broadcast (what the public sees) -->
    <div class="stream-group">
      <div class="stream-group-label">Broadcast</div>
      {#if settingsLoading}
        <p class="stream-muted">Loading…</p>
      {:else}
        <label class="stream-row">
          <span class="stream-row-label">
            Video
            <span class="stream-state" class:off={!videoEnabled}>{videoEnabled ? 'LIVE' : 'BLOCKED'}</span>
          </span>
          <input
            type="checkbox"
            class="stream-toggle"
            checked={videoEnabled}
            disabled={saving}
            on:change={(e) => updateSetting({ video_enabled: e.target.checked })}
          />
        </label>
        <label class="stream-row">
          <span class="stream-row-label">
            Audio
            <span class="stream-state" class:off={!audioEnabled}>{audioEnabled ? 'LIVE' : 'BLOCKED'}</span>
          </span>
          <input
            type="checkbox"
            class="stream-toggle"
            checked={audioEnabled}
            disabled={saving}
            on:change={(e) => updateSetting({ audio_enabled: e.target.checked })}
          />
        </label>
        {#if settingsError}<p class="stream-error">{settingsError}</p>{/if}
      {/if}
    </div>

    <!-- Transmitters (the Pi devices) -->
    <div class="stream-group">
      <div class="stream-group-label">
        Transmitters
        <span class="stream-broker" class:off={!brokerConnected} title="MQTT broker link">
          {brokerConnected ? 'BROKER OK' : 'BROKER DOWN'}
        </span>
      </div>

      {#if devicesLoading}
        <p class="stream-muted">Loading devices…</p>
      {:else if devices.length === 0}
        <p class="stream-muted">No transmitters have reported yet.</p>
      {:else}
        {#each devices as d (d.pi_id)}
          <div class="device-card">
            <div class="device-head">
              <span class="device-name">{d.pi_id}</span>
              <span class="device-status {statusOf(d)}">{statusOf(d).toUpperCase()}</span>
            </div>
            <div class="device-meta">
              {#if d.cpu_temp != null}<span title="CPU temperature">{d.cpu_temp}°C</span>{/if}
              {#if d.status === 'streaming' && d.width}
                <span>{d.width}×{d.height}@{d.fps}</span>
                <span>{d.bitrate}</span>
                {#if d.audio}<span title="Audio enabled">♪</span>{/if}
              {/if}
              {#if d.timestamp}<span class="device-seen" title="Last heartbeat">{d.timestamp}</span>{/if}
            </div>
            {#if d.status === 'error' && d.error}
              <p class="device-error" title={d.error}>{d.error}</p>
            {/if}
            <div class="device-actions">
              <button
                class="device-btn start"
                disabled={pending[d.pi_id] || d.status === 'streaming' || !brokerConnected}
                on:click={() => sendCommand(d.pi_id, 'start')}
              >
                {pending[d.pi_id] ? '…' : 'Start'}
              </button>
              <button
                class="device-btn stop"
                disabled={pending[d.pi_id] || d.status !== 'streaming' || !brokerConnected}
                on:click={() => sendCommand(d.pi_id, 'stop')}
              >
                {pending[d.pi_id] ? '…' : 'Stop'}
              </button>
            </div>

            {#if scheduleForms[d.pi_id]}
              <div class="device-schedule">
                <label class="sched-toggle">
                  <input
                    type="checkbox"
                    class="stream-toggle"
                    bind:checked={scheduleForms[d.pi_id].enabled}
                    disabled={!brokerConnected}
                  />
                  <span>Schedule broadcast window</span>
                </label>
                <div class="sched-times" class:disabled={!scheduleForms[d.pi_id].enabled}>
                  <input
                    type="time"
                    class="sched-time"
                    bind:value={scheduleForms[d.pi_id].start}
                    disabled={!scheduleForms[d.pi_id].enabled || !brokerConnected}
                  />
                  <span class="sched-dash">–</span>
                  <input
                    type="time"
                    class="sched-time"
                    bind:value={scheduleForms[d.pi_id].end}
                    disabled={!scheduleForms[d.pi_id].enabled || !brokerConnected}
                  />
                  <button
                    class="sched-save"
                    disabled={schedPending[d.pi_id] || !brokerConnected}
                    on:click={() => saveSchedule(d.pi_id)}
                  >
                    {schedPending[d.pi_id] ? '…' : 'Save'}
                  </button>
                </div>
                <p class="sched-hint">
                  {#if scheduleForms[d.pi_id].enabled}
                    Broadcasts {scheduleForms[d.pi_id].start}–{scheduleForms[d.pi_id].end} (device local time); rests otherwise.
                  {:else}
                    Always on — enable to limit broadcasting to set hours.
                  {/if}
                </p>
              </div>
            {/if}
          </div>
        {/each}
      {/if}
      {#if devicesError}<p class="stream-error">{devicesError}</p>{/if}
    </div>
  </div>
</div>
