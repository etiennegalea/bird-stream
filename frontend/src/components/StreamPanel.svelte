<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { temperatureState } from '../deviceStatus.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/StreamPanel.css';

  const dispatch = createEventDispatcher();

  // ── Broadcast settings (public video/audio blocking) ────────────────────
  let videoEnabled = true;
  let audioEnabled = false; // matches server default: audio is opt-in
  let privateEnabled = false;
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
  let expandedDevices = {}; // pi_id -> false when manually collapsed
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
        privateEnabled = data.private_enabled;
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
        privateEnabled = data.private_enabled;
        settingsError = '';
        dispatch('settingschange', data);
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
              mode: s.mode || 'sun',
              // In sun mode s.start/end are the computed sunrise/sunset; keep
              // sensible fixed-mode defaults for the pickers.
              start: (s.mode === 'fixed' && s.start) || '06:00',
              end: (s.mode === 'fixed' && s.end) || '20:00',
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

  async function sendCameraCommand(piId, cameraId, action) {
    const key = `${piId}/${cameraId}`;
    pending = { ...pending, [key]: true };
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/stream/devices/${piId}/cameras/${cameraId}/${action}`,
        { method: 'POST', headers: authHeader() },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        devicesError = body.detail || `Failed to ${action} camera`;
      } else {
        devicesError = '';
      }
    } catch {
      devicesError = 'Network error';
    }
    setTimeout(async () => {
      await fetchDevices();
      pending = { ...pending, [key]: false };
    }, 1500);
  }

  async function setCameraEnabled(piId, cameraId, enabled) {
    const key = `${piId}/${cameraId}/enabled`;
    pending = { ...pending, [key]: true };
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/stream/devices/${piId}/cameras/${cameraId}/enabled`,
        {
          method: 'POST',
          headers: authHeader(),
          body: JSON.stringify({ enabled }),
        },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        devicesError = body.detail || 'Failed to update camera';
      } else {
        devicesError = '';
      }
    } catch {
      devicesError = 'Network error';
    }
    setTimeout(async () => {
      await fetchDevices();
      pending = { ...pending, [key]: false };
    }, 1500);
  }

  async function setCameraAutomation(piId, patch) {
    const key = `${piId}/automation`;
    const device = devices.find((item) => item.pi_id === piId);
    const current = device?.camera_automation || {};
    const next = { ...current, ...patch };
    if (!next.auto_manage_pov) next.bird_triggered_pov = false;
    pending = { ...pending, [key]: true };
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/stream/devices/${piId}/camera-automation`,
        {
          method: 'POST',
          headers: authHeader(),
          body: JSON.stringify({
            auto_manage_pov: !!next.auto_manage_pov,
            bird_triggered_pov: !!next.bird_triggered_pov,
          }),
        },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        devicesError = body.detail || 'Failed to update POV automation';
      } else {
        devicesError = '';
        device.camera_automation = {
          ...current,
          ...(await resp.json()),
        };
        devices = devices;
      }
    } catch {
      devicesError = 'Network error';
    } finally {
      pending = { ...pending, [key]: false };
    }
  }

  function isPovCamera(camera) {
    if ((camera.role || '').trim().toLowerCase() === 'pov') return true;
    return ['camera_id', 'label'].some(
      (key) => (camera[key] || '').trim().toLowerCase() === 'pov',
    );
  }

  function isPrimaryCamera(camera, index, streams) {
    const hasExplicitPrimary = streams.some((item) => item.primary);
    return !!camera.primary || (!hasExplicitPrimary && index === 0);
  }

  async function saveSchedule(piId) {
    const form = scheduleForms[piId];
    if (!form) return;
    schedPending = { ...schedPending, [piId]: true };
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/stream/devices/${piId}/schedule`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({
          enabled: form.enabled,
          mode: form.mode,
          start: form.start,
          end: form.end,
        }),
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

  function toggleDevice(piId) {
    const isExpanded = expandedDevices[piId] !== false;
    expandedDevices = {
      ...expandedDevices,
      [piId]: !isExpanded,
    };
  }

  onMount(() => {
    fetchSettings();
    fetchDevices();
    pollTimer = setInterval(fetchDevices, 5000);
  });
  onDestroy(() => {
    clearInterval(pollTimer);
  });
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
        <label class="stream-row">
          <span class="stream-row-label">
            Admin-only viewing
            <span
              class="stream-state"
              class:private={privateEnabled}
            >{privateEnabled ? 'PRIVATE' : 'PUBLIC'}</span>
          </span>
          <input
            type="checkbox"
            class="stream-toggle"
            checked={privateEnabled}
            disabled={saving}
            on:change={(e) => updateSetting({
              private_enabled: e.target.checked,
            })}
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
          {@const temperature = temperatureState(d.cpu_temp)}
          <div
            class="device-card"
            class:collapsed={expandedDevices[d.pi_id] === false}
          >
            <button
              type="button"
              class="device-summary"
              on:click={() => toggleDevice(d.pi_id)}
              aria-expanded={expandedDevices[d.pi_id] !== false}
              aria-controls={`device-${d.pi_id}-details`}
            >
              <div class="device-head">
                <span class="device-chevron" aria-hidden="true">›</span>
                <span class="device-name">{d.pi_id}</span>
                <span class="device-status {statusOf(d)}">{statusOf(d).toUpperCase()}</span>
              </div>
              <div class="device-meta">
                {#if temperature}
                  <span
                    class="device-temperature {temperature.level}"
                    title={temperature.description}
                    aria-label={`${d.cpu_temp} degrees Celsius, ${temperature.description}`}
                  >
                    {d.cpu_temp}°C · {temperature.label}
                  </span>
                {/if}
                {#if d.status === 'streaming' && d.width}
                  <span>{d.width}×{d.height}@{d.fps}</span>
                  <span>{d.bitrate}</span>
                  {#if d.audio}<span title="Audio enabled">♪</span>{/if}
                {/if}
                {#if d.timestamp}<span class="device-seen" title="Last heartbeat">{d.timestamp}</span>{/if}
              </div>
            </button>

            <!-- Keep the controls mounted. Expanding/collapsing only toggles
                 the native hidden style, so MQTT refreshes are unrelated. -->
            <div
              class="device-details"
              id={`device-${d.pi_id}-details`}
              hidden={expandedDevices[d.pi_id] === false}
            >
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

                <div class="camera-list">
                  {#each d.streams || [] as camera, cameraIndex (camera.camera_id)}
                {@const cameraKey = `${d.pi_id}/${camera.camera_id}`}
                {@const primaryCamera = isPrimaryCamera(camera, cameraIndex, d.streams || [])}
                <div class="camera-card" class:disabled={!camera.enabled}>
                  <div class="camera-head">
                    <div>
                      <span class="camera-name">
                        {camera.label}
                        {#if isPovCamera(camera) && !primaryCamera}
                          <span class="camera-role">POV</span>
                        {/if}
                      </span>
                      <span class="camera-path">{camera.path}</span>
                    </div>
                    <label class="camera-enabled-toggle" title="Show this camera publicly">
                      <span>{camera.enabled ? 'Enabled' : 'Disabled'}</span>
                      <input
                        type="checkbox"
                        class="stream-toggle"
                        checked={camera.enabled}
                        disabled={pending[`${cameraKey}/enabled`] || !brokerConnected ||
                          (d.camera_automation?.auto_manage_pov && !primaryCamera)}
                        on:change={(e) => setCameraEnabled(
                          d.pi_id, camera.camera_id, e.target.checked)}
                      />
                    </label>
                  </div>
                  <div class="device-meta">
                    <span class="device-status {camera.status || 'unknown'}">
                      {(camera.status || 'unknown').toUpperCase()}
                    </span>
                    <span>{camera.device}</span>
                    {#if camera.status === 'streaming' && camera.width}
                      <span>{camera.width}×{camera.height}@{camera.fps}</span>
                    {/if}
                  </div>
                  {#if camera.error}
                    <p class="device-error" title={camera.error}>{camera.error}</p>
                  {/if}
                  <div class="device-actions compact">
                    <button
                      class="device-btn start"
                      disabled={!camera.enabled || pending[cameraKey] ||
                        camera.status === 'streaming' || !brokerConnected}
                      on:click={() => sendCameraCommand(
                        d.pi_id, camera.camera_id, 'start')}
                    >
                      {pending[cameraKey] ? '…' : 'Start'}
                    </button>
                    <button
                      class="device-btn stop"
                      disabled={pending[cameraKey] ||
                        camera.status !== 'streaming' || !brokerConnected}
                      on:click={() => sendCameraCommand(
                        d.pi_id, camera.camera_id, 'stop')}
                    >
                      {pending[cameraKey] ? '…' : 'Stop'}
                    </button>
                  </div>
                </div>
                  {/each}
                </div>

                <div class="device-automation">
                  <label class="automation-toggle">
                    <span>
                      <strong>Automatically manage POV camera</strong>
                      <small>Enable secondary cameras marked <code>role: pov</code> and disable other secondary cameras.</small>
                    </span>
                    <input
                      type="checkbox"
                      class="stream-toggle"
                      checked={d.camera_automation?.auto_manage_pov || false}
                      disabled={pending[`${d.pi_id}/automation`]}
                      on:change={(e) => setCameraAutomation(d.pi_id, {
                        auto_manage_pov: e.target.checked,
                      })}
                    />
                  </label>

                  {#if d.camera_automation?.auto_manage_pov && d.camera_automation?.has_pov_camera}
                    <label class="automation-toggle nested">
                      <span>
                        <strong>Bird-triggered POV stream</strong>
                        <small>Start after a bird alert is sent; stop when that bird is gone.</small>
                      </span>
                      <input
                        type="checkbox"
                        class="stream-toggle"
                        checked={d.camera_automation?.bird_triggered_pov || false}
                        disabled={pending[`${d.pi_id}/automation`]}
                        on:change={(e) => setCameraAutomation(d.pi_id, {
                          bird_triggered_pov: e.target.checked,
                        })}
                      />
                    </label>
                  {:else if d.camera_automation?.auto_manage_pov}
                    <p class="automation-warning">No secondary camera is marked <code>role: pov</code>.</p>
                  {/if}
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

                {#if scheduleForms[d.pi_id].enabled}
                  {@const sun = scheduleForms[d.pi_id].mode === 'sun'}
                  <div class="sched-mode">
                    <label class="sched-mode-opt">
                      <input type="radio" value="sun" bind:group={scheduleForms[d.pi_id].mode} disabled={!brokerConnected} />
                      Sunrise → Sunset
                    </label>
                    <label class="sched-mode-opt">
                      <input type="radio" value="fixed" bind:group={scheduleForms[d.pi_id].mode} disabled={!brokerConnected} />
                      Fixed hours
                    </label>
                  </div>

                  <!-- In sun mode the pickers are kept but disabled, showing the
                       device's actual computed sunrise/sunset for today. -->
                  <div class="sched-times">
                    {#if sun}
                      <input type="time" class="sched-time" value={(d.schedule && d.schedule.start) || ''} disabled title="Today's sunrise" />
                      <span class="sched-dash">–</span>
                      <input type="time" class="sched-time" value={(d.schedule && d.schedule.end) || ''} disabled title="Today's sunset" />
                      <span class="sched-suffix">sunrise – sunset</span>
                    {:else}
                      <input type="time" class="sched-time" bind:value={scheduleForms[d.pi_id].start} disabled={!brokerConnected} />
                      <span class="sched-dash">–</span>
                      <input type="time" class="sched-time" bind:value={scheduleForms[d.pi_id].end} disabled={!brokerConnected} />
                    {/if}
                  </div>
                {/if}

                <div class="sched-actions">
                  <p class="sched-hint">
                    {#if !scheduleForms[d.pi_id].enabled}
                      Always on — enable to rest the device outside set hours.
                    {:else if scheduleForms[d.pi_id].mode === 'sun'}
                      Wakes at sunrise, rests at sunset (device local time).
                    {:else}
                      Broadcasts the set hours (device local time); rests otherwise.
                    {/if}
                  </p>
                  <button
                    class="sched-save"
                    disabled={schedPending[d.pi_id] || !brokerConnected}
                    on:click={() => saveSchedule(d.pi_id)}
                  >
                    {schedPending[d.pi_id] ? '…' : 'Save'}
                  </button>
                </div>
                  </div>
                {/if}
            </div>
          </div>
        {/each}
      {/if}
      {#if devicesError}<p class="stream-error">{devicesError}</p>{/if}
    </div>
  </div>
</div>
