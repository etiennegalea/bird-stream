<script>
  import { createEventDispatcher } from 'svelte';
  import { groupStreamsByDevice } from '../streamCatalog.js';

  export let streams = [];
  export let playerStates = {};
  export let hiddenPaths = new Set();

  const dispatch = createEventDispatcher();

  $: groups = groupStreamsByDevice(streams);

  function attachMedia(node, mediaStream) {
    function update(nextMediaStream) {
      if (node.srcObject === nextMediaStream) return;
      node.srcObject = nextMediaStream || null;
      if (nextMediaStream) node.play?.().catch(() => {});
    }

    update(mediaStream);
    return {
      update,
      destroy() {
        node.srcObject = null;
      },
    };
  }
</script>

<div class="streams-panel">
  <div class="panel-header">
    <div>
      <h2>Secondary streams</h2>
      <p>Choose which cameras appear over the main stream.</p>
    </div>
    <button
      type="button"
      class="close-btn"
      aria-label="Close secondary streams"
      on:click={() => dispatch('close')}
    >✕</button>
  </div>

  <div class="stream-list">
    {#if streams.length === 0}
      <div class="empty-state">
        No secondary streams are currently available.
      </div>
    {:else}
      {#each groups as group (group.pi_id)}
        <section class="device-group">
          <h3>{group.pi_id}</h3>
          {#each group.streams as stream (stream.path)}
            {@const state = playerStates[stream.path] || {}}
            <article class="stream-card">
              <button
                type="button"
                class="stream-select-btn"
                aria-label={`Show ${stream.label} from ${stream.pi_id} as the main stream`}
                on:click={() => dispatch('select', { path: stream.path })}
              >
                <div class="preview">
                  <video
                    use:attachMedia={state.mediaStream}
                    autoplay
                    muted
                    playsinline
                    aria-label={`${stream.label} preview`}
                  >
                    <track kind="captions" label="Captions" />
                  </video>
                  {#if !state.mediaStream}
                    <div class="preview-state">
                      {state.error ? 'Stream unavailable' : 'Connecting…'}
                    </div>
                  {/if}
                </div>
              </button>

              <div class="stream-row">
                <div class="stream-identity">
                  <strong>{stream.label}</strong>
                  <span class:connected={state.connected}>
                    {state.connected ? 'Live' : 'Connecting'}
                  </span>
                </div>
                <label class="visibility-toggle">
                  <input
                    type="checkbox"
                    checked={!hiddenPaths.has(stream.path)}
                    aria-label={`Show ${stream.label} over the main stream`}
                    on:change={(event) => dispatch('visibilitychange', {
                      path: stream.path,
                      hidden: !event.currentTarget.checked,
                    })}
                  />
                  <span class="toggle-track" aria-hidden="true"></span>
                  <span class="toggle-label">Visible</span>
                </label>
              </div>
            </article>
          {/each}
        </section>
      {/each}
    {/if}
  </div>
</div>

<style>
  .streams-panel {
    width: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: #fff;
  }

  .panel-header {
    flex: 0 0 auto;
    min-height: 64px;
    padding: 0.85rem 1rem;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    border-bottom: 1px solid #eee;
    box-sizing: border-box;
  }

  .panel-header h2 {
    margin: 0;
    color: #333;
    font-size: 0.9rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .panel-header p {
    margin: 0.25rem 0 0;
    color: #888;
    font-size: 0.66rem;
    line-height: 1.35;
  }

  .close-btn {
    flex: 0 0 auto;
    border: 0;
    padding: 0.15rem;
    color: #aaa;
    background: none;
    font-size: 0.9rem;
    cursor: pointer;
  }

  .close-btn:hover,
  .close-btn:focus-visible {
    color: #B35610;
    outline: none;
  }

  .stream-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 0.85rem;
  }

  .device-group + .device-group {
    margin-top: 1rem;
  }

  .device-group h3 {
    margin: 0 0 0.45rem;
    color: #888;
    font-size: 0.62rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .stream-card {
    overflow: hidden;
    border: 1px solid #e4e4e4;
    border-radius: 7px;
    background: #fafafa;
  }

  .stream-card + .stream-card {
    margin-top: 0.7rem;
  }

  .stream-select-btn {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }

  .stream-select-btn:hover .preview {
    filter: brightness(1.08);
  }

  .stream-select-btn:focus-visible {
    outline: 2px solid var(--accent, #B35610);
    outline-offset: -2px;
  }

  .preview {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    background: #0b0b0b;
  }

  .preview video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    background: #0b0b0b;
  }

  .preview-state {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: #aaa;
    background: rgba(10, 10, 10, 0.72);
    font-size: 0.7rem;
  }

  .stream-row {
    min-height: 48px;
    padding: 0.55rem 0.65rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    box-sizing: border-box;
  }

  .stream-identity {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
  }

  .stream-identity strong {
    overflow: hidden;
    color: #333;
    font-size: 0.74rem;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .stream-identity span {
    color: #999;
    font-size: 0.58rem;
  }

  .stream-identity span.connected {
    color: #3b7f48;
  }

  .visibility-toggle {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 0.35rem;
    cursor: pointer;
  }

  .visibility-toggle input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
  }

  .toggle-track {
    position: relative;
    width: 30px;
    height: 17px;
    border-radius: 999px;
    background: #bbb;
    transition: background 0.15s;
  }

  .toggle-track::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    transition: transform 0.15s;
  }

  .visibility-toggle input:checked + .toggle-track {
    background: var(--accent, #B35610);
  }

  .visibility-toggle input:checked + .toggle-track::after {
    transform: translateX(13px);
  }

  .visibility-toggle input:focus-visible + .toggle-track {
    outline: 2px solid #E87530;
    outline-offset: 2px;
  }

  .toggle-label {
    width: 38px;
    color: #777;
    font-size: 0.62rem;
  }

  .empty-state {
    padding: 2rem 1rem;
    color: #999;
    font-size: 0.75rem;
    line-height: 1.5;
    text-align: center;
  }
</style>
