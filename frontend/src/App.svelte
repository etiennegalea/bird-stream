<script>
  import { onMount } from 'svelte';
  import Auth from './components/Auth.svelte';
  import ChatRoom from './components/ChatRoom.svelte';
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

  // Auth overlay state
  let authView = null;       // null = hidden, else 'login' | 'signup' | 'forgot' | 'reset' | 'verify'
  let resetToken = '';
  let verifyToken = '';

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

  function getRandomName(prefix = 'client_') {
    return prefix + Math.random().toString(36).substring(2, 15);
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

      const response = await fetch(`${getApiBaseUrl()}/webrtc/offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: getRandomName(),
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

  function handleLogout() {
    auth.logout();
  }

  onMount(() => {
    // Handle special URL tokens for email verification and password reset.
    const params = new URLSearchParams(window.location.search);
    const vt = params.get('verify-token');
    const rt = params.get('reset-token');

    if (vt) {
      verifyToken = vt;
      authView = 'verify';
      // Clean the token from the URL bar without a page reload.
      history.replaceState(null, '', window.location.pathname);
    } else if (rt) {
      resetToken = rt;
      authView = 'reset';
      history.replaceState(null, '', window.location.pathname);
    }

    setupPeerCountWs();
    startStream();

    return () => {
      cleanup();
      if (peerCountWs) peerCountWs.close();
    };
  });
</script>

<div class="app-container">
  <div class="header">
    <h1>BIRB STREAM</h1>
    <p>Bringing you beautiful <b>{city}</b> birbs live!</p>

    <div class="auth-header">
      {#if $auth}
        <span class="auth-username">👤 {$auth.user.username}</span>
        <button class="auth-btn secondary" on:click={handleLogout}>Log out</button>
      {:else}
        <button class="auth-btn" on:click={() => authView = 'login'}>Log in</button>
        <button class="auth-btn secondary" on:click={() => authView = 'signup'}>Sign up</button>
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

    <button
      class="chat-toggle-btn"
      class:chat-hidden={!isChatVisible}
      on:click={toggleChat}
      aria-label={isChatVisible ? 'Hide chat' : 'Show chat'}
    >
      <img src="/chat_icon.svg" alt="Chat Icon" />
      <span class="notification-marker" class:seen={!hasUnreadMessages}></span>
    </button>

    <div class="chat-section" class:chat-hidden={!isChatVisible}>
      <ChatRoom onNewMessage={handleNewMessage} {isChatVisible} />
    </div>
  </div>
</div>

{#if authView}
  <Auth
    view={authView}
    {resetToken}
    {verifyToken}
    on:authenticated={() => { authView = null; }}
    on:close={() => { authView = null; }}
  />
{/if}

<style>
  .auth-header {
    position: absolute;
    top: 1rem;
    right: 1.25rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .auth-username {
    font-size: 0.85rem;
    color: #ccc;
  }

  .auth-btn {
    padding: 0.35rem 0.85rem;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    background: #7c6fe0;
    color: #fff;
    transition: background 0.15s;
  }
  .auth-btn:hover { background: #6a5ecb; }
  .auth-btn.secondary {
    background: transparent;
    border: 1px solid #555;
    color: #ccc;
  }
  .auth-btn.secondary:hover { border-color: #888; color: #fff; }
</style>
