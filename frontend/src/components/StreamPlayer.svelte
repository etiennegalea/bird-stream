<script>
  import { createEventDispatcher, onDestroy, onMount } from 'svelte';
  import Hls from 'hls.js';
  import LoadingCircleDots from './LoadingCircleDots.svelte';
  import { streamUrls } from '../streamCatalog.js';

  export let stream;
  export let streamBase;
  export let enableHlsFallback = false;
  export let isMain = false;
  export let audioAllowed = false;

  const dispatch = createEventDispatcher();

  let videoEl;
  let peerConnection = null;
  let hls = null;
  let statsInterval = null;
  let statsState = null;
  let destroyed = false;
  let connected = false;
  let error = null;
  let fallbackStarted = false;

  $: if (videoEl && (!isMain || !audioAllowed) && !videoEl.muted) {
    videoEl.muted = true;
  }

  function report(patch = {}) {
    dispatch('state', {
      path: stream.path,
      connected,
      error,
      fps: 0,
      ...patch,
    });
  }

  function waitForIceGathering(pc, timeoutMs = 2000) {
    return new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve();
      const timer = setTimeout(resolve, timeoutMs);
      pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') {
          clearTimeout(timer);
          resolve();
        }
      });
    });
  }

  function stopStats() {
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = null;
    statsState = null;
  }

  function startStats() {
    stopStats();
    if (!isMain || !peerConnection) return;
    statsInterval = setInterval(async () => {
      if (!peerConnection) return;
      try {
        const stats = await peerConnection.getStats();
        stats.forEach((entry) => {
          if (entry.type !== 'inbound-rtp' || entry.kind !== 'video') return;
          let fps = 0;
          if (statsState) {
            const frames = entry.framesReceived - statsState.frames;
            const elapsed = entry.timestamp - statsState.timestamp;
            fps = elapsed > 0 ? Math.round((frames / elapsed) * 1000) : 0;
          }
          statsState = {
            frames: entry.framesReceived,
            timestamp: entry.timestamp,
          };
          report({ fps });
        });
      } catch (_) {
        // A closing peer can race one final stats read.
      }
    }, 1000);
  }

  function closeMedia() {
    stopStats();
    if (peerConnection) peerConnection.close();
    peerConnection = null;
    if (hls) hls.destroy();
    hls = null;
    if (videoEl) {
      videoEl.srcObject = null;
      videoEl.removeAttribute('src');
    }
  }

  function markConnected() {
    if (destroyed) return;
    connected = true;
    error = null;
    startStats();
    report();
  }

  function startHls() {
    if (destroyed || fallbackStarted) return;
    fallbackStarted = true;
    error = null;
    const urls = streamUrls(streamBase, stream.path);
    const onPlaying = () => markConnected();

    if (videoEl?.canPlayType('application/vnd.apple.mpegurl')) {
      videoEl.src = urls.hls;
      videoEl.addEventListener('playing', onPlaying, { once: true });
      videoEl.play?.().catch(() => {});
      return;
    }
    if (Hls.isSupported()) {
      hls = new Hls({ lowLatencyMode: true });
      hls.loadSource(urls.hls);
      hls.attachMedia(videoEl);
      videoEl.addEventListener('playing', onPlaying, { once: true });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal || destroyed) return;
        connected = false;
        error = 'Stream unavailable';
        report();
      });
      return;
    }
    error = 'Unsupported stream';
    report();
  }

  async function connect() {
    closeMedia();
    fallbackStarted = false;
    connected = false;
    error = null;
    report();

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: ['stun:stun.l.google.com:19302'] }],
        bundlePolicy: 'max-bundle',
      });
      peerConnection = pc;
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.addTransceiver('audio', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (!destroyed && videoEl && event.streams[0]) {
          videoEl.srcObject = event.streams[0];
        }
      };
      pc.onconnectionstatechange = () => {
        if (destroyed || pc !== peerConnection) return;
        if (pc.connectionState === 'connected') {
          markConnected();
        } else if (['disconnected', 'failed'].includes(pc.connectionState)) {
          connected = false;
          stopStats();
          if (enableHlsFallback && !fallbackStarted) {
            pc.close();
            peerConnection = null;
            startHls();
          } else {
            error = 'Connection lost';
            report();
          }
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      if (destroyed || pc !== peerConnection) return;

      const response = await fetch(streamUrls(streamBase, stream.path).whep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: pc.localDescription.sdp,
      });
      if (!response.ok) {
        throw new Error(`WHEP request failed (${response.status})`);
      }
      const answer = await response.text();
      if (!destroyed && pc === peerConnection) {
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      }
    } catch (reason) {
      if (destroyed) return;
      peerConnection?.close();
      peerConnection = null;
      if (enableHlsFallback) {
        startHls();
      } else {
        error = reason?.message || 'Stream unavailable';
        report();
      }
    }
  }

  function enforceMuted() {
    if ((!isMain || !audioAllowed) && videoEl && !videoEl.muted) {
      videoEl.muted = true;
    }
  }

  onMount(connect);
  onDestroy(() => {
    destroyed = true;
    closeMedia();
  });
</script>

<div class="player" class:main={isMain} class:thumbnail={!isMain}>
  <video
    bind:this={videoEl}
    controls={isMain}
    autoplay
    muted
    playsinline
    class:audio-blocked={!audioAllowed || !isMain}
    on:volumechange={enforceMuted}
    aria-label={`${stream.label} from ${stream.pi_id}`}
  >
    <track kind="captions" label="Captions" />
  </video>

  {#if !connected && !error}
    <div class="player-state loading" aria-label={`Connecting to ${stream.label}`}>
      <LoadingCircleDots />
    </div>
  {:else if error}
    <div class="player-state error">
      <span>{error}</span>
      {#if isMain}
        <button type="button" on:click={connect}>Retry</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .player {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: #0b0b0b;
  }

  video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #0b0b0b;
  }

  .thumbnail video {
    object-fit: cover;
    pointer-events: none;
  }

  .player-state {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    background: rgba(10, 10, 10, 0.72);
    color: #fff;
    font-size: 0.7rem;
    text-align: center;
  }

  .main .player-state {
    font-size: 0.9rem;
  }

  .player-state button {
    border: 0;
    border-radius: 5px;
    padding: 0.4rem 0.8rem;
    color: #fff;
    background: #B35610;
    cursor: pointer;
  }

  video.audio-blocked::-webkit-media-controls-volume-slider,
  video.audio-blocked::-webkit-media-controls-mute-button,
  video.audio-blocked::-webkit-media-controls-volume-control-container {
    display: none !important;
  }
</style>
