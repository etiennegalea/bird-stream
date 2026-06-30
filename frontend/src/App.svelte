<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import Auth from './components/Auth.svelte';
  import ChatRoom from './components/ChatRoom.svelte';
  import UserSettings from './components/UserSettings.svelte';
  import Weather from './components/Weather.svelte';
  import LoadingCircleDots from './components/LoadingCircleDots.svelte';
  import { auth } from './stores/auth.js';
  import { getApiBaseUrl } from './utils.js';

  let isConnected = false;
  let error = null;
  let isChatVisible = true;
  let hasUnreadMessages = false;
  let viewerCount = 0;
  let fps = 0;
  let city = '...';

  let videoEl;
  let peerConnection = null;
  let peerCountWs = null;
  let statsInterval = null;
  let statsState = null;

  let authView = null;       // null = hidden, else 'login' | 'signup' | 'forgot' | 'reset' | 'verify'
  let resetToken = '';
  let verifyToken = '';
  let isSettingsOpen = false;
  let isMenuOpen = false;
  let menuWrapEl;

  function handleWindowClick(e) {
    if (isMenuOpen && menuWrapEl && !menuWrapEl.contains(e.target)) {
      isMenuOpen = false;
    }
  }

  function startFpsTracking() {
    if (statsInterval) clearInterval(statsInterval);
    statsState = null;
    statsInterval = setInterval(async () => {
      if (!peerConnection) return;
      try {
        const stats = await peerConnection.getStats();
        stats.forEach(report => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') {
            if (statsState) {
              const framesDelta = report.framesReceived - statsState.lastFramesReceived;
              const timeDelta = report.timestamp - statsState.lastTimestamp;
              fps = Math.round((framesDelta / timeDelta) * 1000);
            }
            statsState = { lastFramesReceived: report.framesReceived, lastTimestamp: report.timestamp };
          }
        });
      } catch (err) {
        console.error('Error getting WebRTC stats:', err);
      }
    }, 1000);
  }

  function stopFpsTracking() {
    if (statsInterval) {
      clearInterval(statsInterval);
      statsInterval = null;
    }
  }

  function setupPeerCountWs() {
    const ws = new WebSocket(`${getApiBaseUrl(true)}/peer-count`);
    ws.onmessage = (event) => {
      viewerCount = JSON.parse(event.data).count;
    };
    ws.onclose = () => setTimeout(setupPeerCountWs, 5000);
    peerCountWs = ws;
  }

  function getPeerId() {
    const key = 'birb_peer_id';
    let id = localStorage.getItem(key);
    if (!id) {
      id = 'client_' + Math.random().toString(36).substring(2, 15);
      localStorage.setItem(key, id);
    }
    return id;
  }

  function cleanup() {
    stopFpsTracking();
    if (peerConnection) {
      peerConnection.close();
      peerConnection = null;
    }
    if (videoEl) {
      videoEl.srcObject = null;
    }
  }

  async function startStream() {
    cleanup();
    try {
      const pc = new RTCPeerConnection({
        iceServers: [
          { urls: ['stun:stun.l.google.com:19302'] },
          {
            urls: [
              'turn:turn.lifeofarobin.com:3478?transport=udp',
              'turn:turn.lifeofarobin.com:5349?transport=udp'
            ],
            username: 'user',
            credential: 'supersecretpassword'
          }
        ],
        iceTransportPolicy: 'all',
        bundlePolicy: 'max-bundle',
        rtcpMuxPolicy: 'require'
      });

      pc.ontrack = (event) => {
        if (videoEl && event.streams[0]) {
          videoEl.srcObject = event.streams[0];
        }
      };

      pc.onconnectionstatechange = () => {
        switch (pc.connectionState) {
          case 'connected':
            isConnected = true;
            startFpsTracking();
            break;
          case 'disconnected':
          case 'failed':
            isConnected = false;
            stopFpsTracking();
            error = 'Connection lost. Please refresh to try again.';
            break;
        }
      };

      peerConnection = pc;

      const offer = await pc.createOffer({
        offerToReceiveVideo: true,
        offerToReceiveAudio: true
      });
      await pc.setLocalDescription(offer);

      const authState = get(auth);
      const headers = { 'Content-Type': 'application/json' };
      if (authState?.token) {
        headers['Authorization'] = `Bearer ${authState.token}`;
      }

      const response = await fetch(`${getApiBaseUrl()}/webrtc/offer`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          id: getPeerId(),
          offer: { type: offer.type, sdp: offer.sdp }
        })
      });

      if (!response.ok) throw new Error('Failed to connect to server');

      const answerData = await response.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answerData));

      const remoteStream = pc.getRemoteStreams()[0];
      if (videoEl && remoteStream) {
        videoEl.srcObject = remoteStream;
      } else {
        console.error('Failed to get remote stream');
      }
    } catch (err) {
      console.error('Error setting up WebRTC:', err);
      error = 'Failed to connect to camera stream. Please refresh to try again.';
    }
  }

  function handleNewMessage() {
    if (!isChatVisible) {
      hasUnreadMessages = true;
    }
  }

  function toggleChat() {
    isChatVisible = !isChatVisible;
    if (isChatVisible) {
      hasUnreadMessages = false;
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
          auth.updateUser({ username: data.username, avatar: data.avatar, bio: data.bio });
        }
      } catch (_) { /* non-critical */ }
    }

    setupPeerCountWs();
    startStream();

    return () => {
      cleanup();
      if (peerCountWs) peerCountWs.close();
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
        {#if !isConnected && !error}
          <LoadingCircleDots />
        {/if}
        {#if error}
          <div class="error-message">{error}</div>
        {:else}
          <video
            bind:this={videoEl}
            controls
            autoplay
            playsinline
            class="stream-viewport"
          >
            <track kind="captions" label="Captions" />
          </video>
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
    background: #1c1c1c;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 0.4rem 0;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    z-index: 200;
  }

  .menu-username {
    padding: 0.4rem 0.85rem 0.3rem;
    font-size: 0.8rem;
    color: #888;
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .menu-divider {
    border: none;
    border-top: 1px solid #2e2e2e;
    margin: 0.25rem 0;
  }

  .menu-item {
    display: block;
    width: 100%;
    padding: 0.45rem 0.85rem;
    background: none;
    border: none;
    color: #ddd;
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .menu-item:hover { background: #8C3523; color: #fff; }

  .side-buttons {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 0 0 36px;
    padding: 8px 0;
    gap: 8px;
  }
</style>
