<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import AdminPanel from './components/AdminPanel.svelte';
  import StreamPanel from './components/StreamPanel.svelte';
  import StreamsPanel from './components/StreamsPanel.svelte';
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
    secondaryStreams as listSecondaryStreams,
  } from './streamCatalog.js';
  import {
    clampThumbnailPosition,
    clampThumbnailSize,
  } from './thumbnailLayout.js';
  import { getApiBaseUrl } from './utils.js';

  // Stream endpoints (MediaMTX via traefik, same-origin). Override for local
  // dev against a bare MediaMTX with VITE_STREAM_URL=http://localhost:8889-style base.
  const streamBase = import.meta.env.VITE_STREAM_URL || window.location.origin;
  // HLS fallback when WebRTC/WHEP can't connect (e.g. UDP-blocked networks).
  // Controlled from .env via VITE_HLS_FALLBACK — baked in at BUILD time, so
  // changing it requires: docker compose build frontend.
  const ENABLE_HLS_FALLBACK = import.meta.env.VITE_HLS_FALLBACK === 'true';

  let isConnected = false;
  let error = null;
  let isChatVisible = true;
  let unreadMessageCount = 0;
  let viewerCount = 0;
  let fps = 0;
  let city = '...';
  let streamCatalog = [];
  let availableStreams = [];
  let secondaryStreams = [];
  let streamGroups = [];
  let thumbnailGroupStartPaths = new Set();
  let selectedStreamPath = null;
  let selectedStream = null;
  let catalogTimer = null;
  let playbackReady = false;
  let playerStates = {};
  let streamStageEl;
  let thumbnailPositions = {};
  let thumbnailSizes = {};
  let thumbnailDrag = null;
  let thumbnailResize = null;
  let draggedStreamPath = null;
  let resizedStreamPath = null;
  let hiddenSecondaryPaths = new Set();

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
  let privateEnabled = true; // fail closed until the backend responds
  let privacyKnown = false;
  let streamAccessToken = null;
  let streamAccessTokenExpiresAt = 0;
  let activatingPlayback = false;
  let isStreamPanelOpen = false;
  let isStreamsPanelOpen = false;
  let suppressPanelTransitions = false;
  let streamSettingsWs = null;
  let streamsChanged = false;
  let devicesChanged = false;
  let knownSecondaryStreamPaths = null;
  let knownDeviceIds = null;
  let deviceInventoryTimer = null;
  let authValidationTimer = null;

  $: isAdmin = !!$auth?.user?.is_admin;
  $: isAnyPanelOpen = isChatVisible || isAdminPanelOpen
    || isStreamPanelOpen || isStreamsPanelOpen;
  $: showStreamLabels = isAdmin && isAdminPanelOpen;
  $: canViewStreams = privacyKnown && (!privateEnabled || isAdmin);
  $: streamGroups = groupStreamsByDevice(streamCatalog);
  // Keep every player in this stable, device-grouped order. Switching the
  // selected path then changes only CSS/controls; no WHEP player is remounted.
  $: availableStreams = streamGroups.flatMap(group => group.streams);
  $: secondaryStreams = listSecondaryStreams(
    availableStreams,
    selectedStreamPath,
  );
  $: thumbnailGroupStartPaths = new Set(
    streamGroups
      .map(group => group.streams.find(
        stream => stream.path !== selectedStreamPath)?.path)
      .filter(Boolean),
  );
  $: selectedStream = availableStreams.find(
    stream => stream.path === selectedStreamPath);
  $: isConnected = !!playerStates[selectedStreamPath]?.connected;
  $: fps = playerStates[selectedStreamPath]?.fps || 0;

  function viewerCanAccess() {
    return privacyKnown && (!privateEnabled || isAdmin);
  }

  async function fetchStreamCatalog({ reconnectIfChanged = true } = {}) {
    if (!viewerCanAccess()) return;
    if (privateEnabled && isAdmin && !(await ensureStreamAccessToken())) return;
    try {
      const authState = get(auth);
      const headers = authState?.token
        ? { 'Authorization': `Bearer ${authState.token}` }
        : {};
      const resp = await fetch(`${getApiBaseUrl()}/stream/catalog`, { headers });
      if (!resp.ok) return;
      const data = await resp.json();
      const next = data.streams || [];
      const previousPath = selectedStreamPath;
      streamCatalog = next;
      selectedStreamPath = chooseMainStreamPath(next, previousPath);
      const nextSecondaryKey = transmittedStreams(next)
        .filter(stream => stream.path !== selectedStreamPath)
        .map(stream => stream.path)
        .sort()
        .join('\n');
      if (
        knownSecondaryStreamPaths !== null
        && knownSecondaryStreamPaths !== nextSecondaryKey
        && !isStreamsPanelOpen
      ) {
        streamsChanged = true;
      }
      knownSecondaryStreamPaths = nextSecondaryKey;
      const activePaths = new Set(
        transmittedStreams(next).map(stream => stream.path));
      playerStates = Object.fromEntries(
        Object.entries(playerStates)
          .filter(([path]) => activePaths.has(path)),
      );
      thumbnailPositions = Object.fromEntries(
        Object.entries(thumbnailPositions)
          .filter(([path]) => activePaths.has(path)),
      );
      thumbnailSizes = Object.fromEntries(
        Object.entries(thumbnailSizes)
          .filter(([path]) => activePaths.has(path)),
      );
      hiddenSecondaryPaths = new Set(
        [...hiddenSecondaryPaths].filter(path => activePaths.has(path)),
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

  async function fetchDeviceInventory() {
    const authState = get(auth);
    if (!authState?.token || !authState?.user?.is_admin) return;
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/stream/devices`,
        { headers: { 'Authorization': `Bearer ${authState.token}` } },
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const nextDeviceIds = (data.devices || [])
        .map(device => device.pi_id)
        .filter(Boolean)
        .sort()
        .join('\n');
      if (
        knownDeviceIds !== null
        && knownDeviceIds !== nextDeviceIds
        && !isStreamPanelOpen
      ) {
        devicesChanged = true;
      }
      knownDeviceIds = nextDeviceIds;
    } catch (_) {
      // Retain the last successful inventory during brief API interruptions.
    }
  }

  async function validateAuthSession() {
    const authState = get(auth);
    if (!authState?.token) return true;
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
        headers: { 'Authorization': `Bearer ${authState.token}` },
      });
      if (resp.status === 401) {
        auth.logout();
        window.location.reload();
        return false;
      }
      if (resp.ok && (await resp.json()).is_blocked) {
        auth.logout();
        window.location.reload();
        return false;
      }
      return resp.ok;
    } catch {
      // A temporarily unavailable server is not the same as an invalid token.
      return true;
    }
  }

  async function ensureStreamAccessToken() {
    if (!privateEnabled) return true;
    if (!isAdmin) return false;
    if (
      streamAccessToken
      && streamAccessTokenExpiresAt > Date.now() + 60_000
    ) {
      return true;
    }
    const authState = get(auth);
    if (!authState?.token) return false;
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/stream-access-token`,
        {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${authState.token}` },
        },
      );
      if (!resp.ok) return false;
      const data = await resp.json();
      streamAccessToken = data.token;
      streamAccessTokenExpiresAt = Date.now()
        + ((data.expires_in || 600) * 1000);
      return true;
    } catch (_) {
      return false;
    }
  }

  function stopPrivatePlayback() {
    cleanup();
    isStreamsPanelOpen = false;
    streamCatalog = [];
    selectedStreamPath = null;
    error = null;
    streamAccessToken = null;
    streamAccessTokenExpiresAt = 0;
  }

  async function activatePlayback() {
    if (!viewerCanAccess() || activatingPlayback) return;
    activatingPlayback = true;
    try {
      if (privateEnabled && !(await ensureStreamAccessToken())) {
        error = 'The stream is not currently available.';
        return;
      }
      await fetchStreamCatalog({ reconnectIfChanged: false });
      enterQueue();
    } finally {
      activatingPlayback = false;
    }
  }

  function applyStreamSettings(data) {
    const wasViewable = privacyKnown && (!privateEnabled || isAdmin);
    videoAllowed = data.video_enabled;
    audioAllowed = data.audio_enabled;
    privateEnabled = !!data.private_enabled;
    privacyKnown = true;
    const isViewable = !privateEnabled || isAdmin;

    if (!isViewable) {
      stopPrivatePlayback();
    } else if (!wasViewable) {
      void activatePlayback();
    } else if (privateEnabled && isAdmin) {
      void ensureStreamAccessToken();
    }
  }

  async function fetchStreamSettings() {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/stream/settings`);
      if (!resp.ok) return;
      applyStreamSettings(await resp.json());
    } catch (_) {
      // Remain fail-closed until settings can be loaded.
    }
  }

  function selectStream(path) {
    if (!path || path === selectedStreamPath) return;
    selectedStreamPath = path;
  }

  function tileForPath(path) {
    return [...(streamStageEl?.querySelectorAll('[data-stream-path]') || [])]
      .find(tile => tile.dataset.streamPath === path);
  }

  function clampLayoutForPath(path) {
    const position = thumbnailPositions[path];
    const tile = tileForPath(path);
    if (
      !position
      || !tile
      || !streamStageEl
      || tile.classList.contains('viewport-secondary-hidden')
    ) return;

    const stageRect = streamStageEl.getBoundingClientRect();
    const tileRect = tile.getBoundingClientRect();
    const viewportSize = {
      width: stageRect.width,
      height: stageRect.height,
    };
    let tileSize = {
      width: tileRect.width,
      height: tileRect.height,
    };
    const configuredSize = thumbnailSizes[path];
    if (configuredSize) {
      const clampedSize = clampThumbnailSize(
        configuredSize.width,
        position,
        viewportSize,
      );
      tileSize = clampedSize;
      if (
        clampedSize.width !== configuredSize.width
        || clampedSize.height !== configuredSize.height
      ) {
        thumbnailSizes = {
          ...thumbnailSizes,
          [path]: clampedSize,
        };
      }
    }
    const clampedPosition = clampThumbnailPosition(
      position,
      tileSize,
      viewportSize,
    );
    if (
      clampedPosition.x !== position.x
      || clampedPosition.y !== position.y
    ) {
      thumbnailPositions = {
        ...thumbnailPositions,
        [path]: clampedPosition,
      };
    }
  }

  function clampAllThumbnailLayouts() {
    for (const path of Object.keys(thumbnailPositions)) {
      clampLayoutForPath(path);
    }
  }

  function observeStreamStage(node) {
    if (typeof ResizeObserver === 'undefined') return {};
    const observer = new ResizeObserver(clampAllThumbnailLayouts);
    observer.observe(node);
    return {
      destroy() {
        observer.disconnect();
      },
    };
  }

  function startThumbnailDrag(event, path) {
    if (event.button !== 0 || !streamStageEl) return;
    const tile = tileForPath(path);
    if (!tile) return;

    const stageRect = streamStageEl.getBoundingClientRect();
    const tileRect = tile.getBoundingClientRect();
    thumbnailDrag = {
      path,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: tileRect.left - stageRect.left,
      originY: tileRect.top - stageRect.top,
      width: tileRect.width,
      height: tileRect.height,
    };
    draggedStreamPath = path;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
  }

  function moveThumbnail(event) {
    if (!thumbnailDrag || event.pointerId !== thumbnailDrag.pointerId) return;
    const stageRect = streamStageEl?.getBoundingClientRect();
    if (!stageRect) return;

    const position = clampThumbnailPosition(
      {
        x: thumbnailDrag.originX + event.clientX - thumbnailDrag.startX,
        y: thumbnailDrag.originY + event.clientY - thumbnailDrag.startY,
      },
      { width: thumbnailDrag.width, height: thumbnailDrag.height },
      { width: stageRect.width, height: stageRect.height },
    );
    thumbnailPositions = {
      ...thumbnailPositions,
      [thumbnailDrag.path]: position,
    };
    event.preventDefault();
  }

  function endThumbnailDrag(event) {
    if (!thumbnailDrag || event.pointerId !== thumbnailDrag.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    thumbnailDrag = null;
    draggedStreamPath = null;
    event.stopPropagation();
  }

  function moveThumbnailWithKeyboard(event, path) {
    const movement = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    }[event.key];
    if (!movement || !streamStageEl) return;

    const tile = tileForPath(path);
    if (!tile) return;
    const stageRect = streamStageEl.getBoundingClientRect();
    const tileRect = tile.getBoundingClientRect();
    const current = thumbnailPositions[path] || {
      x: tileRect.left - stageRect.left,
      y: tileRect.top - stageRect.top,
    };
    const step = event.shiftKey ? 1 : 10;
    thumbnailPositions = {
      ...thumbnailPositions,
      [path]: clampThumbnailPosition(
        {
          x: current.x + movement[0] * step,
          y: current.y + movement[1] * step,
        },
        { width: tileRect.width, height: tileRect.height },
        { width: stageRect.width, height: stageRect.height },
      ),
    };
    event.preventDefault();
    event.stopPropagation();
  }

  function startThumbnailResize(event, path) {
    if (event.button !== 0 || !streamStageEl) return;
    const tile = tileForPath(path);
    if (!tile) return;

    const stageRect = streamStageEl.getBoundingClientRect();
    const tileRect = tile.getBoundingClientRect();
    const position = thumbnailPositions[path] || {
      x: tileRect.left - stageRect.left,
      y: tileRect.top - stageRect.top,
    };
    thumbnailPositions = {
      ...thumbnailPositions,
      [path]: position,
    };
    thumbnailResize = {
      path,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: tileRect.width,
      position,
    };
    resizedStreamPath = path;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
  }

  function moveThumbnailResize(event) {
    if (
      !thumbnailResize
      || event.pointerId !== thumbnailResize.pointerId
      || !streamStageEl
    ) return;
    const stageRect = streamStageEl.getBoundingClientRect();
    const horizontalWidth = thumbnailResize.startWidth
      + event.clientX - thumbnailResize.startX;
    const verticalWidth = thumbnailResize.startWidth
      + (event.clientY - thumbnailResize.startY) * (16 / 9);
    const desiredWidth = Math.abs(
      horizontalWidth - thumbnailResize.startWidth,
    ) >= Math.abs(verticalWidth - thumbnailResize.startWidth)
      ? horizontalWidth
      : verticalWidth;
    thumbnailSizes = {
      ...thumbnailSizes,
      [thumbnailResize.path]: clampThumbnailSize(
        desiredWidth,
        thumbnailResize.position,
        { width: stageRect.width, height: stageRect.height },
      ),
    };
    event.preventDefault();
  }

  function endThumbnailResize(event) {
    if (
      !thumbnailResize
      || event.pointerId !== thumbnailResize.pointerId
    ) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    thumbnailResize = null;
    resizedStreamPath = null;
    event.stopPropagation();
  }

  function resizeThumbnailWithKeyboard(event, path) {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(
      event.key,
    ) || !streamStageEl) return;
    const tile = tileForPath(path);
    if (!tile) return;

    const stageRect = streamStageEl.getBoundingClientRect();
    const tileRect = tile.getBoundingClientRect();
    const position = thumbnailPositions[path] || {
      x: tileRect.left - stageRect.left,
      y: tileRect.top - stageRect.top,
    };
    const grows = event.key === 'ArrowRight' || event.key === 'ArrowDown';
    const step = event.shiftKey ? 1 : 10;
    thumbnailPositions = {
      ...thumbnailPositions,
      [path]: position,
    };
    thumbnailSizes = {
      ...thumbnailSizes,
      [path]: clampThumbnailSize(
        tileRect.width + (grows ? step : -step),
        position,
        { width: stageRect.width, height: stageRect.height },
      ),
    };
    event.preventDefault();
    event.stopPropagation();
  }

  function hideSecondaryStream(event, path) {
    event.stopPropagation();
    hiddenSecondaryPaths = new Set([...hiddenSecondaryPaths, path]);
  }

  function handlePlayerState(event) {
    const state = event.detail;
    playerStates = { ...playerStates, [state.path]: state };
    sendViewerPresence();
  }

  function handleWindowClick(e) {
    if (isMenuOpen && menuWrapEl && !menuWrapEl.contains(e.target)) {
      isMenuOpen = false;
    }
  }

  function setupStreamSettingsWs() {
    const ws = new WebSocket(`${getApiBaseUrl(true)}/stream-settings`);
    ws.onmessage = (event) => {
      applyStreamSettings(JSON.parse(event.data));
    };
    ws.onclose = () => setTimeout(setupStreamSettingsWs, 5000);
    streamSettingsWs = ws;
  }

  function setupPeerCountWs() {
    const ws = new WebSocket(`${getApiBaseUrl(true)}/peer-count`);
    ws.onopen = sendViewerPresence;
    ws.onmessage = (event) => {
      viewerCount = JSON.parse(event.data).count;
    };
    ws.onclose = () => setTimeout(setupPeerCountWs, 5000);
    peerCountWs = ws;
  }

  function sendViewerPresence() {
    if (peerCountWs?.readyState !== WebSocket.OPEN) return;
    peerCountWs.send(JSON.stringify({
      viewing: !!playerStates[selectedStreamPath]?.connected,
    }));
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
    sendViewerPresence();
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

  async function reconnect() {
    cleanup();
    if (privateEnabled && !(await ensureStreamAccessToken())) {
      error = 'The stream is not currently available.';
      return;
    }
    enterQueue();
  }

  function handleNewMessage() {
    if (!isChatVisible) {
      unreadMessageCount = Math.min(unreadMessageCount + 1, 999);
    }
  }

  function suppressPanelSwitchAnimation() {
    suppressPanelTransitions = true;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        suppressPanelTransitions = false;
      });
    });
  }

  function toggleChat() {
    if (!isChatVisible) {
      if (isAnyPanelOpen) suppressPanelSwitchAnimation();
      isChatVisible = true;
      isAdminPanelOpen = false;
      isStreamPanelOpen = false;
      isStreamsPanelOpen = false;
      unreadMessageCount = 0;
    } else {
      isChatVisible = false;
    }
  }

  function toggleAdmin() {
    if (!isAdminPanelOpen) {
      if (isAnyPanelOpen) suppressPanelSwitchAnimation();
      isAdminPanelOpen = true;
      isChatVisible = false;
      isStreamPanelOpen = false;
      isStreamsPanelOpen = false;
    } else {
      isAdminPanelOpen = false;
    }
  }

  function toggleStreamPanel() {
    if (!isStreamPanelOpen) {
      if (isAnyPanelOpen) suppressPanelSwitchAnimation();
      isStreamPanelOpen = true;
      devicesChanged = false;
      isChatVisible = false;
      isAdminPanelOpen = false;
      isStreamsPanelOpen = false;
    } else {
      isStreamPanelOpen = false;
    }
  }

  function toggleStreamsPanel() {
    if (!isStreamsPanelOpen) {
      if (isAnyPanelOpen) suppressPanelSwitchAnimation();
      isStreamsPanelOpen = true;
      streamsChanged = false;
      isChatVisible = false;
      isAdminPanelOpen = false;
      isStreamPanelOpen = false;
    } else {
      isStreamsPanelOpen = false;
    }
  }

  function handleSecondaryVisibility(event) {
    const { path, hidden } = event.detail;
    const nextHidden = new Set(hiddenSecondaryPaths);
    if (hidden) {
      nextHidden.add(path);
    } else {
      nextHidden.delete(path);
    }
    hiddenSecondaryPaths = nextHidden;
    if (!hidden) {
      requestAnimationFrame(() => clampLayoutForPath(path));
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
          if (data.is_blocked) {
            auth.logout();
            window.location.reload();
            return;
          }
          auth.updateUser({
            username: data.username,
            avatar: data.avatar,
            bio: data.bio,
            is_admin: data.is_admin,
            bird_notification_email: data.bird_notification_email,
            auto_join_chat: data.auto_join_chat,
          });
        } else if (resp.status === 401) {
          auth.logout();
          window.location.reload();
          return;
        }
      } catch (_) { /* non-critical */ }
    }
    authValidationTimer = setInterval(validateAuthSession, 30_000);

    setupPeerCountWs();
    setupStreamSettingsWs();
    await fetchStreamSettings();
    if (viewerCanAccess()) {
      await activatePlayback();
    }
    catalogTimer = setInterval(fetchStreamCatalog, 5000);
    await fetchDeviceInventory();
    deviceInventoryTimer = setInterval(fetchDeviceInventory, 5000);

    return () => {
      cleanup();
      clearInterval(catalogTimer);
      clearInterval(deviceInventoryTimer);
      clearInterval(authValidationTimer);
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

  <div
    class="main-content"
    class:panel-hidden={!isAnyPanelOpen}
    class:panel-switching={suppressPanelTransitions}
  >
    <div class="stream-section">
      <div class="stream-viewport">
        {#if !privacyKnown || !canViewStreams}
          <div class="stream-waiting">
            The stream is not currently available.
          </div>
        {:else if queuePosition !== null}
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
          <div
            class="multi-stream-stage"
            bind:this={streamStageEl}
            use:observeStreamStage
          >
            {#each availableStreams as camera (camera.path)}
              {@const isMainStream = camera.path === selectedStreamPath}
              <!-- The same keyed element changes size and position without
                   remounting or reconnecting its WHEP session. -->
              <div
                class="stream-tile"
                class:main-stream={isMainStream}
                class:stream-thumbnail={!isMainStream}
                class:positioned-thumbnail={
                  !isMainStream && !!thumbnailPositions[camera.path]}
                class:labels-visible={showStreamLabels}
                class:dragging-thumbnail={
                  !isMainStream && draggedStreamPath === camera.path}
                class:resizing-thumbnail={
                  !isMainStream && resizedStreamPath === camera.path}
                class:viewport-secondary-hidden={
                  !isMainStream && (
                    isStreamsPanelOpen
                    || hiddenSecondaryPaths.has(camera.path)
                  )}
                class:thumbnail-device-start={
                  !isMainStream && thumbnailGroupStartPaths.has(camera.path)}
                data-stream-path={camera.path}
                data-main-stream={isMainStream}
                data-hidden={
                  !isMainStream && hiddenSecondaryPaths.has(camera.path)}
                style={!isMainStream
                  ? [
                    thumbnailPositions[camera.path]
                      ? `left: ${thumbnailPositions[camera.path].x}px; top: ${thumbnailPositions[camera.path].y}px;`
                      : '',
                    thumbnailSizes[camera.path]
                      ? `width: ${thumbnailSizes[camera.path].width}px; height: ${thumbnailSizes[camera.path].height}px;`
                      : '',
                  ].join(' ')
                  : undefined}
                on:transitionend={() => {
                  if (!isMainStream) clampLayoutForPath(camera.path);
                }}
              >
                <StreamPlayer
                  stream={camera}
                  {streamBase}
                  enableHlsFallback={ENABLE_HLS_FALLBACK}
                  isMain={isMainStream}
                  audioAllowed={isMainStream && audioAllowed}
                  accessToken={privateEnabled ? streamAccessToken : null}
                  on:state={handlePlayerState}
                />

                {#if isMainStream && showStreamLabels}
                  <div class="main-stream-label">
                    <span>{camera.label}</span>
                    <small>{camera.pi_id}</small>
                  </div>
                {:else if !isMainStream}
                  <button
                    type="button"
                    class="stream-promote-target"
                    aria-label={`Show ${camera.label} from ${camera.pi_id} as main stream`}
                    title="Show as main stream"
                    on:click={() => selectStream(camera.path)}
                  ></button>
                  <div class="stream-tile-toolbar">
                    <button
                      type="button"
                      class="stream-drag-handle"
                      aria-label={`Move ${camera.label}`}
                      title="Drag to move"
                      on:pointerdown={(event) => startThumbnailDrag(event, camera.path)}
                      on:pointermove={moveThumbnail}
                      on:pointerup={endThumbnailDrag}
                      on:pointercancel={endThumbnailDrag}
                      on:keydown={(event) => moveThumbnailWithKeyboard(
                        event,
                        camera.path,
                      )}
                      on:click|stopPropagation
                    >
                      <span aria-hidden="true">⠿</span>
                    </button>
                    {#if showStreamLabels}
                      <span class="stream-tile-label">
                        <span>{camera.label}</span>
                        <small>{camera.pi_id}</small>
                      </span>
                    {/if}
                    <button
                      type="button"
                      class="stream-minimize-btn"
                      aria-label={`Hide ${camera.label}`}
                      title="Hide from main viewport"
                      on:click={(event) => hideSecondaryStream(
                        event,
                        camera.path,
                      )}
                    >
                      <span aria-hidden="true">−</span>
                    </button>
                  </div>
                  <button
                    type="button"
                    class="stream-resize-handle"
                    aria-label={`Resize ${camera.label}`}
                    title="Drag to resize"
                    on:pointerdown={(event) => startThumbnailResize(
                      event,
                      camera.path,
                    )}
                    on:pointermove={moveThumbnailResize}
                    on:pointerup={endThumbnailResize}
                    on:pointercancel={endThumbnailResize}
                    on:keydown={(event) => resizeThumbnailWithKeyboard(
                      event,
                      camera.path,
                    )}
                    on:click|stopPropagation
                  >
                    <span aria-hidden="true">◢</span>
                  </button>
                {/if}
              </div>
            {/each}
          </div>

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
        {#if canViewStreams}
          <div class="viewer-count">
            <img src="/viewers_icon.svg" alt="viewers" />
            <span>{viewerCount}</span>
            <div class="info-container">
              <span class="label">FPS</span>
              <span class="value">{fps}</span>
            </div>
          </div>
        {/if}
        <div class="weather-info">
          <Weather onCityChange={(name) => city = name} />
        </div>
        {#if canViewStreams}
          <div class="connection-status">
            {isConnected ? '🟢' : '🔴'}
          </div>
        {/if}
      </div>
    </div>

    <div class="chat-section" class:chat-hidden={!isChatVisible}>
      <ChatRoom
        onNewMessage={handleNewMessage}
        {isChatVisible}
        autoJoin={$auth?.user?.auto_join_chat ?? false}
        onSignInClick={() => { authView = 'login'; }}
      />
    </div>

    <div
      class="streams-panel-section"
      class:streams-panel-hidden={!isStreamsPanelOpen}
    >
      {#if isStreamsPanelOpen}
        <StreamsPanel
          streams={secondaryStreams}
          {playerStates}
          hiddenPaths={hiddenSecondaryPaths}
          on:close={() => isStreamsPanelOpen = false}
          on:visibilitychange={handleSecondaryVisibility}
        />
      {/if}
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
            on:settingschange={(event) => applyStreamSettings(event.detail)}
          />
        {/if}
      </div>
    {/if}

    <div class="side-buttons">
      <button
        class="chat-toggle-btn"
        class:active={isChatVisible}
        on:click={toggleChat}
        aria-label={isChatVisible
          ? 'Hide chat'
          : unreadMessageCount > 0
            ? `Show chat, ${unreadMessageCount} unread ${unreadMessageCount === 1 ? 'message' : 'messages'}`
            : 'Show chat'}
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M16.16 18.383a9.645 9.645 0 0 1-2.843.421 9.146 9.146 0 0 1-4.865-1.345 11.567 11.567 0 0 0 2.348.241 11.132 11.132 0 0 0 4.608-.978c.073-.021.148-.037.22-.059a1.8 1.8 0 0 1 .531-.08 1.8 1.8 0 0 1 1.055.341l.441.319-.05-.171a1.8 1.8 0 0 1 .485-1.806 4.069 4.069 0 0 0 1.048-1.586 6.919 6.919 0 0 0 1.251-3.619 5.069 5.069 0 0 1 .727 2.593 5.407 5.407 0 0 1-1.784 3.914c.8 2.738 1.138 3.594.564 3.912a.6.6 0 0 1-.3.085c-.454 0-1.163-.538-3.436-2.182Zm-11.941-.807c-.573-.318-.234-1.174.564-3.911A5.407 5.407 0 0 1 3 9.75c0-3.4 3.492-6.15 7.8-6.15s7.8 2.753 7.8 6.15-3.492 6.15-7.8 6.15a9.642 9.642 0 0 1-2.842-.421c-2.273 1.644-2.983 2.182-3.437 2.182a.6.6 0 0 1-.302-.085Zm.58-7.826a3.65 3.65 0 0 0 1.227 2.612 1.8 1.8 0 0 1 .485 1.806l-.05.171.441-.319a1.8 1.8 0 0 1 1.055-.342 1.8 1.8 0 0 1 .531.08 7.828 7.828 0 0 0 2.312.341c3.252 0 6-1.992 6-4.35s-2.748-4.35-6-4.35-6 1.993-6 4.351Z"/>
        </svg>
        {#if unreadMessageCount > 0}
          <span class="notification-marker">
            {unreadMessageCount > 99 ? '99+' : unreadMessageCount}
          </span>
        {/if}
      </button>
      <button
        class="streams-toggle-btn"
        class:active={isStreamsPanelOpen}
        on:click={toggleStreamsPanel}
        aria-label={isStreamsPanelOpen
          ? 'Close secondary streams'
          : streamsChanged
            ? 'Open secondary streams, list changed'
          : 'Open secondary streams'}
        aria-expanded={isStreamsPanelOpen}
        title="Secondary streams"
        disabled={!canViewStreams || (secondaryStreams.length === 0 && !streamsChanged)}
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M4 5h11v8H4V5zm13 3h3v11H8v-4h9V8z"/>
        </svg>
        {#if streamsChanged}
          <span class="panel-change-marker" aria-hidden="true"></span>
        {/if}
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
          aria-label={isStreamPanelOpen
            ? 'Close stream panel'
            : devicesChanged
              ? 'Open stream panel, device list changed'
              : 'Open stream panel'}
          aria-expanded={isStreamPanelOpen}
          title="Stream panel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
          </svg>
          {#if devicesChanged}
            <span class="panel-change-marker" aria-hidden="true"></span>
          {/if}
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
    color: #fff;
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
    margin-left: 2px;
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

  .streams-toggle-btn {
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
  .streams-toggle-btn:hover:not(:disabled) {
    background: #fff;
    color: #B35610;
    border-color: #e0c8b8;
  }
  .streams-toggle-btn.active {
    background: #B35610;
    color: #fff;
    border-color: #B35610;
  }
  .streams-toggle-btn:disabled {
    cursor: default;
    opacity: 0.4;
  }

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
