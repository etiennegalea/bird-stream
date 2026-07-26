<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import AdminPanel from './components/AdminPanel.svelte';
  import StreamPanel from './components/StreamPanel.svelte';
  import Auth from './components/Auth.svelte';
  import ChatRoom from './components/ChatRoom.svelte';
  import StreamPlayer from './components/StreamPlayer.svelte';
  import UserSettings from './components/UserSettings.svelte';
  import Weather from './components/Weather.svelte';
  import { auth } from './stores/auth.js';
  import {
    availableStreams as transmittedStreams,
    chooseMainStreamPath,
    groupStreamsByDevice,
  } from './streamCatalog.js';
  import { getApiBaseUrl } from './utils.js';

  // Stream endpoints (MediaMTX via traefik, same-origin). Override for local
  // dev against a bare MediaMTX with VITE_STREAM_URL=http://localhost:8889-style base.
  const streamBase = import.meta.env.VITE_STREAM_URL || window.location.origin;
  // HLS fallback when WebRTC/WHEP can't connect (e.g. UDP-blocked networks).
  // Controlled from .env via VITE_HLS_FALLBACK — baked in at BUILD time, so
  // changing it requires: docker compose build frontend.
  const ENABLE_HLS_FALLBACK = import.meta.env.VITE_HLS_FALLBACK !== 'false';

  let isConnected = false;
  let error = null;
  let isChatVisible = true;
  let hasUnreadMessages = false;
  let viewerCount = 0;
  let fps = 0;
  let city = '...';
  let streamCatalog = [];
  let availableStreams = [];
  let streamGroups = [];
  let thumbnailGroups = [];
  let selectedStreamPath = null;
  let selectedStream = null;
  let catalogTimer = null;
  let playbackReady = false;
  let playerStates = {};

  let peerCountWs = null;

  let queuePosition = null;
  let queueWs = null;

  let authView = null;       // null = hidden, else 'login' | 'signup' | 'forgot' | 'reset' | 'verify'
  let resetToken = '';
  let verifyToken = '';
  let isSettingsOpen = false;
  let isAdminPanelOpen = false;
  let isMenuOpen = false;
  let menuWrapEl;

  // Global stream toggles (admin-controlled, enforced for every viewer).
  let videoAllowed = true;
  let audioAllowed = false; // matches server default: audio is opt-in
  let isStreamPanelOpen = false;
  let streamSettingsWs = null;
  let activeDeviceId = null;

  $: availableStreams = transmittedStreams(streamCatalog);
  $: streamGroups = groupStreamsByDevice(streamCatalog);
  $: thumbnailGroups = streamGroups
    .map(group => ({
      ...group,
      streams: group.streams.filter(
        stream => stream.path !== selectedStreamPath),
    }))
    .filter(group => group.streams.length);
  $: selectedStream = availableStreams.find(
    stream => stream.path === selectedStreamPath);
  $: activeDeviceId = selectedStream
    ? `${selectedStream.pi_id} / ${selectedStream.label}`
    : null;
  $: isConnected = !!playerStates[selectedStreamPath]?.connected;
  $: fps = playerStates[selectedStreamPath]?.fps || 0;

  async function fetchStreamCatalog({ reconnectIfChanged = true } = {}) {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/stream/catalog`);
      if (!resp.ok) return;
      const data = await resp.json();
      const next = data.streams || [];
      const previousPath = selectedStreamPath;
      streamCatalog = next;
      selectedStreamPath = chooseMainStreamPath(next, previousPath);
      const activePaths = new Set(
        transmittedStreams(next).map(stream => stream.path));
      playerStates = Object.fromEntries(
        Object.entries(playerStates)
          .filter(([path]) => activePaths.has(path)),
      );
      if (!selectedStreamPath) {
        playbackReady = false;
        error = 'No enabled camera stream is currently available.';
      } else {
        error = null;
        if (reconnectIfChanged && !playbackReady && !queueWs) enterQueue();
      }
    } catch (_) {
      // Retain the last catalog during brief API/MQTT interruptions.
    }
  }

  function selectStream(path) {
    if (!path || path === selectedStreamPath) return;
    selectedStreamPath = path;
  }

  function handlePlayerState(event) {
    const state = event.detail;
    playerStates = { ...playerStates, [state.path]: state };
  }

  function handleWindowClick(e) {
    if (isMenuOpen && menuWrapEl && !menuWrapEl.contains(e.target)) {
      isMenuOpen = false;
    }
  }

  function setupStreamSettingsWs() {
    const ws = new WebSocket(`${getApiBaseUrl(true)}/stream-settings`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      videoAllowed = data.video_enabled;
      audioAllowed = data.audio_enabled;
    };
    ws.onclose = () => setTimeout(setupStreamSettingsWs, 5000);
    streamSettingsWs = ws;
  }

  function setupPeerCountWs() {
    const ws = new WebSocket(`${getApiBaseUrl(true)}/peer-count`);
    ws.onmessage = (event) => {
      viewerCount = JSON.parse(event.data).count;
    };
    ws.onclose = () => setTimeout(setupPeerCountWs, 5000);
    peerCountWs = ws;
  }

  function cleanup() {
    if (queueWs) {
      queueWs.onclose = null;
      queueWs.close();
      queueWs = null;
    }
    queuePosition = null;
    playbackReady = false;
    playerStates = {};
  }

  function enterQueue() {
    if (!selectedStreamPath || queueWs) return;
    playbackReady = false;
    error = null;
    const ws = new WebSocket(`${getApiBaseUrl(true)}/queue`);
    queueWs = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'ready') {
        queuePosition = null;
        ws.close();
        queueWs = null;
        playbackReady = true;
      } else if (data.type === 'queued') {
        queuePosition = data.position;
      }
    };

    ws.onerror = () => {
      error = 'Could not connect to stream. Please refresh.';
      queueWs = null;
    };
  }

  function reconnect() {
    cleanup();
    enterQueue();
  }

  function handleNewMessage() {
    if (!isChatVisible) {
      hasUnreadMessages = true;
    }
  }

  function toggleChat() {
    if (!isChatVisible) {
      isChatVisible = true;
      isAdminPanelOpen = false;
      isStreamPanelOpen = false;
      hasUnreadMessages = false;
    } else {
      isChatVisible = false;
    }
  }

  function toggleAdmin() {
    if (!isAdminPanelOpen) {
      isAdminPanelOpen = true;
      isChatVisible = false;
      isStreamPanelOpen = false;
    } else {
      isAdminPanelOpen = false;
    }
  }

  function toggleStreamPanel() {
    if (!isStreamPanelOpen) {
      isStreamPanelOpen = true;
      isChatVisible = false;
      isAdminPanelOpen = false;
    } else {
      isStreamPanelOpen = false;
    }
  }

  onMount(async () => {
    const params = new URLSearchParams(window.location.search);
    const vt = params.get('verify-token');
    const rt = params.get('reset-token');

    if (vt) {
      verifyToken = vt;
      authView = 'verify';
      history.replaceState(null, '', window.location.pathname);
    } else if (rt) {
      resetToken = rt;
      authView = 'reset';
      history.replaceState(null, '', window.location.pathname);
    }

    // Refresh profile so avatar/bio are up to date on page load.
    const authState = get(auth);
    if (authState?.token) {
      try {
        const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
          headers: { 'Authorization': `Bearer ${authState.token}` }
        });
        if (resp.ok) {
          const data = await resp.json();
          auth.updateUser({ username: data.username, avatar: data.avatar, bio: data.bio, is_admin: data.is_admin });
        }
      } catch (_) { /* non-critical */ }
    }

    setupPeerCountWs();
    setupStreamSettingsWs();
    await fetchStreamCatalog({ reconnectIfChanged: false });
    catalogTimer = setInterval(fetchStreamCatalog, 5000);
    enterQueue();

    return () => {
      cleanup();
      clearInterval(catalogTimer);
      if (peerCountWs) peerCountWs.close();
      if (streamSettingsWs) {
        streamSettingsWs.onclose = null; // prevent reconnect
        streamSettingsWs.close();
      }
    };
  });
</script>

<svelte:window on:click={handleWindowClick} />

<div class="app-container">
  <div class="header">
    <h1>BIRB STREAM</h1>
    <p>Bringing you beautiful <b>{city}</b> birbs live!</p>

    <!-- User avatar menu (top-right) -->
    <div class="user-menu-wrap" bind:this={menuWrapEl}>
      <div class="avatar-trigger">
        {#if $auth?.user?.is_admin}
          <span class="admin-tag">ADMIN</span>
        {/if}
        <button
          class="avatar-btn"
          on:click={() => isMenuOpen = !isMenuOpen}
          aria-label="User menu"
          aria-expanded={isMenuOpen}
        >
        {#if $auth?.user?.avatar}
          <img src={$auth.user.avatar} alt="Profile" class="avatar-img" />
        {:else if $auth?.user?.username}
          <span class="avatar-initials">{$auth.user.username.charAt(0).toUpperCase()}</span>
        {:else}
          <svg class="avatar-anon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 12c2.761 0 5-2.239 5-5s-2.239-5-5-5-5 2.239-5 5 2.239 5 5 5zm0 2c-3.332 0-10 1.667-10 5v1h20v-1c0-3.333-6.668-5-10-5z"/>
          </svg>
        {/if}
      </button>
      </div>

      {#if isMenuOpen}
        <div class="user-menu" role="menu">
          {#if $auth}
            <p class="menu-username">{$auth.user.username}</p>
            <hr class="menu-divider" />
            <button class="menu-item" role="menuitem" on:click={() => { isMenuOpen = false; isSettingsOpen = true; }}>Settings</button>
            <button class="menu-item" role="menuitem" on:click={() => { auth.logout(); window.location.reload(); }}>Log out</button>
          {:else}
            <button class="menu-item" role="menuitem" on:click={() => { isMenuOpen = false; authView = 'login'; }}>Log in</button>
            <button class="menu-item" role="menuitem" on:click={() => { isMenuOpen = false; authView = 'signup'; }}>Sign up</button>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <div class="main-content" class:chat-hidden={!isChatVisible}>
    <div class="stream-section">
      <div class="stream-viewport">
        {#if queuePosition !== null}
          <div class="queue-display">
            <p class="queue-label">Stream is full</p>
            <p class="queue-position">#{queuePosition}</p>
            <p class="queue-sublabel">You're in the queue</p>
          </div>
        {:else if error}
          <div class="error-display">
            <p class="error-text">{error}</p>
            <button class="reconnect-btn" on:click={reconnect}>Reconnect</button>
          </div>
        {:else if playbackReady && selectedStream}
          <div class="main-stream">
            <StreamPlayer
              stream={selectedStream}
              {streamBase}
              enableHlsFallback={ENABLE_HLS_FALLBACK}
              isMain={true}
              {audioAllowed}
              on:state={handlePlayerState}
            />
            {#if activeDeviceId}
              <div class="device-id-badge" title="Transmitter feeding this stream">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
                </svg>
                {activeDeviceId}
              </div>
            {/if}
          </div>

          {#if thumbnailGroups.length}
            <div class="thumbnail-tray" aria-label="Other live camera streams">
              {#each thumbnailGroups as group (group.pi_id)}
                <section class="thumbnail-device-group" aria-label={`Streams from ${group.pi_id}`}>
                  <h3>{group.pi_id}</h3>
                  <div class="thumbnail-row">
                    {#each group.streams as camera (camera.path)}
                      <button
                        type="button"
                        class="stream-thumbnail"
                        on:click={() => selectStream(camera.path)}
                        aria-label={`Show ${camera.label} from ${camera.pi_id} as main stream`}
                        title={`Show ${camera.label} as main stream`}
                      >
                        <StreamPlayer
                          stream={camera}
                          {streamBase}
                          enableHlsFallback={ENABLE_HLS_FALLBACK}
                          isMain={false}
                          audioAllowed={false}
                          on:state={handlePlayerState}
                        />
                        <span class="thumbnail-label">{camera.label}</span>
                      </button>
                    {/each}
                  </div>
                </section>
              {/each}
            </div>
          {/if}

          {#if !videoAllowed}
            <div class="video-disabled-overlay">
              <img src="/birb-no-bg.png" alt="Birb" class="video-disabled-img" />
              <p class="video-disabled-title">Video is currently disabled</p>
              <p class="video-disabled-sub">The camera stream has been turned off by an admin.</p>
            </div>
          {/if}
        {:else}
          <div class="stream-waiting">
            Waiting for a transmitted camera stream…
          </div>
        {/if}
      </div>

      <div class="stream-info">
        <div class="viewer-count">
          <img src="/viewers_icon.svg" alt="viewers" />
          <span>{viewerCount}</span>
          <div class="info-container">
            <span class="label">FPS</span>
            <span class="value">{fps}</span>
          </div>
        </div>
        <div class="weather-info">
          <Weather onCityChange={(name) => city = name} />
        </div>
        <div class="connection-status">
          {isConnected ? '🟢' : '🔴'}
        </div>
      </div>
    </div>

    <div class="chat-section" class:chat-hidden={!isChatVisible}>
      <ChatRoom onNewMessage={handleNewMessage} {isChatVisible} onSignInClick={() => { authView = 'login'; }} />
    </div>

    {#if $auth?.user?.is_admin}
      <div class="admin-section" class:admin-hidden={!isAdminPanelOpen}>
        {#if isAdminPanelOpen}
          <AdminPanel on:close={() => isAdminPanelOpen = false} />
        {/if}
      </div>
      <div class="stream-panel-section" class:stream-panel-hidden={!isStreamPanelOpen}>
        {#if isStreamPanelOpen}
          <StreamPanel
            on:close={() => isStreamPanelOpen = false}
          />
        {/if}
      </div>
    {/if}

    <div class="side-buttons">
      <button
        class="chat-toggle-btn"
        class:chat-hidden={!isChatVisible}
        on:click={toggleChat}
        aria-label={isChatVisible ? 'Hide chat' : 'Show chat'}
      >
        <img src="/chat_icon.svg" alt="Chat Icon" />
        <span class="notification-marker" class:seen={!hasUnreadMessages}></span>
      </button>
      {#if $auth?.user?.is_admin}
        <button
          class="admin-toggle-btn"
          class:active={isAdminPanelOpen}
          on:click={toggleAdmin}
          aria-label={isAdminPanelOpen ? 'Close admin panel' : 'Open admin panel'}
          title="Admin panel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/>
          </svg>
        </button>
        <button
          class="stream-toggle-btn"
          class:active={isStreamPanelOpen}
          class:blocking={!videoAllowed || !audioAllowed}
          on:click={toggleStreamPanel}
          aria-label={isStreamPanelOpen ? 'Close stream panel' : 'Open stream panel'}
          aria-expanded={isStreamPanelOpen}
          title="Stream panel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
          </svg>
        </button>
      {/if}
    </div>
  </div>
</div>

{#if authView}
  <Auth
    view={authView}
    {resetToken}
    {verifyToken}
    on:authenticated={() => { authView = null; window.location.reload(); }}
    on:close={() => { authView = null; }}
  />
{/if}

{#if isSettingsOpen && $auth}
  <UserSettings on:close={() => isSettingsOpen = false} />
{/if}

<style>
  /* User avatar menu */
  .user-menu-wrap {
    position: absolute;
    top: 1rem;
    right: 1.25rem;
  }

  .avatar-trigger {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .admin-tag {
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #fff;
    background: #B35610;
    padding: 2px 6px;
    border-radius: 4px;
    line-height: 1;
    user-select: none;
  }

  .avatar-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid rgba(142, 142, 142, 0.2);
    background: #a9a9a9;
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    transition: border-color 0.15s;
  }
  .avatar-btn:hover {
    background: #c2c2c2;
  }

  .avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .avatar-initials {
    font-size: 0.9rem;
    font-weight: 700;
    color: #fff;
    line-height: 1;
  }

  .avatar-anon {
    width: 20px;
    height: 20px;
    color: #aaa;
  }

  .user-menu {
    position: absolute;
    top: calc(36px + 0.5rem);
    right: 0;
    min-width: 160px;
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 0.4rem 0;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.10);
    z-index: 200;
  }

  .menu-username {
    padding: 0.4rem 0.85rem 0.3rem;
    font-size: 0.8rem;
    color: #aaa;
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .menu-divider {
    border: none;
    border-top: 1px solid #eee;
    margin: 0.25rem 0;
  }

  .menu-item {
    display: block;
    width: 100%;
    padding: 0.45rem 0.85rem;
    background: none;
    border: none;
    color: #444;
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .menu-item:hover { background: #B35610; color: #fff; }

  .side-buttons {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 0 0 36px;
    padding: 8px 0;
    gap: 8px;
  }

  .admin-toggle-btn {
    position: relative;
    width: 32px;
    height: 32px;
    border: 1px solid #ddd;
    border-radius: 8px;
    background: #fafafa;
    color: #aaa;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .admin-toggle-btn:hover { background: #fff; color: #B35610; border-color: #e0c8b8; }
  .admin-toggle-btn.active { background: #B35610; color: #fff; border-color: #B35610; }

  .stream-toggle-btn {
    position: relative;
    width: 32px;
    height: 32px;
    border: 1px solid #ddd;
    border-radius: 8px;
    background: #fafafa;
    color: #aaa;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .stream-toggle-btn:hover { background: #fff; color: #B35610; border-color: #e0c8b8; }
  .stream-toggle-btn.active { background: #B35610; color: #fff; border-color: #B35610; }
  .stream-toggle-btn.blocking::after {
    content: '';
    position: absolute;
    top: -2px;
    right: -2px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #d63a1f;
  }

  /* Transmitter id badge — shown on the viewport while the stream panel is
     open so you can tell which device is feeding the stream. */
  .device-id-badge {
    position: absolute;
    top: 10px;
    left: 10px;
    z-index: 4;
    display: flex;
    align-items: center;
    gap: 0.3rem;
    padding: 3px 8px;
    background: rgba(17, 17, 17, 0.72);
    color: #fff;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    border-radius: 6px;
    pointer-events: none;
  }
  .device-id-badge svg { color: #E87530; }

  /* Video block: opaque overlay on the stream viewport (audio keeps playing). */
  .video-disabled-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #111;
    border-radius: 8px;
    color: #fff;
    gap: 0.25rem;
    z-index: 10;
  }

  .video-disabled-img {
    width: 90px;
    opacity: 0.85;
    margin-bottom: 0.5rem;
  }

  .video-disabled-title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: #E87530;
  }

  .video-disabled-sub {
    margin: 0;
    font-size: 0.8rem;
    color: #888;
  }

</style>
