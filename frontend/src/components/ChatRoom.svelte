<script>
  import { onMount, onDestroy, afterUpdate } from 'svelte';
  import { get } from 'svelte/store';
  import '../styles/ChatRoom.css';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl, generateBirdUsername } from '../utils.js';

  export let onNewMessage = () => {};
  export let isChatVisible = true;

  const authState = get(auth);
  const isLoggedIn = !!authState?.user?.username;

  let username = authState?.user?.username ?? generateBirdUsername();
  let messages = [];
  let newMessage = '';
  let ws = null;
  let messagesEndEl;
  let hasJoined = false;
  let isCycling = false;
  let isSpinning = false;

  // Hover profile popup
  let popup = null;
  let hideTimeout = null;
  const profileCache = {};  // keyed by user_id (number) or "u:username" for legacy

  async function fetchActiveUsernames() {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/chat/usernames`);
      if (resp.ok) return new Set(await resp.json());
    } catch (_) {}
    return new Set();
  }

  async function pickUniqueBirdName(taken) {
    let name;
    let attempts = 0;
    do {
      name = generateBirdUsername();
      attempts++;
    } while (taken.has(name) && attempts < 100);
    return name;
  }

  async function cycleUsername() {
    isCycling = true;
    isSpinning = true;
    const taken = await fetchActiveUsernames();
    username = await pickUniqueBirdName(taken);
    isCycling = false;
  }

  function connectChat() {
    if (ws) ws.close();

    const token = authState?.token ?? '';
    const base = `${getApiBaseUrl(true)}/chat?username=${encodeURIComponent(username)}`;
    const url = token ? `${base}&token=${encodeURIComponent(token)}` : base;
    const chatWs = new WebSocket(url);

    chatWs.onmessage = (event) => {
      const data = JSON.parse(event.data);

      onNewMessage();

      const messageDate = new Date(data.timestamp);
      const now = new Date();
      if (
        messageDate.getDate() !== now.getDate() ||
        messageDate.getMonth() !== now.getMonth() ||
        messageDate.getFullYear() !== now.getFullYear()
      ) {
        const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
        const dateStr = `${messageDate.getDate()} ${months[messageDate.getMonth()]} ${messageDate.getFullYear()}`;
        messages = [...messages, { type: 'system', text: dateStr, timestamp: messageDate.getTime() }];
      }

      if (data.type === 'history') {
        messages = data.messages.filter(msg => msg.type !== 'system');
      } else if (data.type === 'message') {
        messages = [...messages, data];
      } else if (data.type === 'system' && !data.text.includes(username)) {
        messages = [...messages, data];
      }
    };

    chatWs.onerror = (err) => console.error('Chat WebSocket error:', err);
    ws = chatWs;
  }

  async function joinChat() {
    if (!isLoggedIn) {
      const taken = await fetchActiveUsernames();
      if (taken.has(username)) {
        username = await pickUniqueBirdName(taken);
      }
    }
    hasJoined = true;
    connectChat();
  }

  async function showUserPopup(userId, hovUsername, event) {
    clearTimeout(hideTimeout);
    const rect = event.currentTarget.getBoundingClientRect();
    const popupWidth = 190;
    const spaceRight = window.innerWidth - rect.right - 10;
    const x = spaceRight >= popupWidth ? rect.right + 6 : rect.left - popupWidth - 6;
    const y = Math.max(8, Math.min(rect.top - 8, window.innerHeight - 200));

    const cacheKey = userId != null ? userId : `u:${hovUsername}`;
    popup = { cacheKey, x, y, profile: cacheKey in profileCache ? profileCache[cacheKey] : undefined };

    if (!(cacheKey in profileCache)) {
      try {
        const url = userId != null
          ? `${getApiBaseUrl()}/auth/profile/public/id/${userId}`
          : `${getApiBaseUrl()}/auth/profile/public/${encodeURIComponent(hovUsername)}`;
        const resp = await fetch(url);
        profileCache[cacheKey] = resp.ok ? await resp.json() : null;
      } catch (_) {
        profileCache[cacheKey] = null;
      }
      if (popup?.cacheKey === cacheKey) {
        popup = { ...popup, profile: profileCache[cacheKey] };
      }
    }
  }

  function hideUserPopup() {
    hideTimeout = setTimeout(() => { popup = null; }, 150);
  }

  function cancelHidePopup() {
    clearTimeout(hideTimeout);
  }

  onMount(async () => {
    if (!isLoggedIn) {
      const taken = await fetchActiveUsernames();
      if (taken.has(username)) {
        username = await pickUniqueBirdName(taken);
      }
    }
  });

  afterUpdate(() => {
    if (hasJoined && isChatVisible && messagesEndEl) {
      messagesEndEl.scrollIntoView({ behavior: 'smooth' });
    }
  });

  function handleSendMessage(e) {
    e.preventDefault();
    if (!newMessage.trim() || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ username, text: newMessage, timestamp: new Date().toISOString() }));
    newMessage = '';
  }

  function buildMessageGroups(msgs) {
    const groups = [];
    let current = null;
    for (const msg of msgs) {
      if (msg.type === 'system') {
        current = null;
        groups.push({ type: 'system', msg, key: `sys-${msg.timestamp}` });
        continue;
      }
      const gk = msg.user_id != null ? `uid-${msg.user_id}` : `guest-${msg.username}`;
      if (!current || current.gk !== gk) {
        current = {
          type: 'user', gk,
          key: `${gk}-${msg.timestamp}`,
          username: msg.username,
          user_id: msg.user_id ?? null,
          avatar: msg.avatar ?? null,
          is_account: !!msg.is_account,
          is_me: msg.username === username,
          messages: [],
        };
        groups.push(current);
      }
      current.messages.push(msg);
    }
    return groups;
  }

  $: messageGroups = buildMessageGroups(messages);

  onDestroy(() => {
    if (ws) ws.close();
    clearTimeout(hideTimeout);
  });
</script>

<div class="chat-messages">
  {#if !hasJoined}
    <div class="join-prompt">
      <svg class="join-bird-icon" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <ellipse cx="32" cy="36" rx="18" ry="14" fill="#e8e0d8"/>
        <circle cx="32" cy="20" r="12" fill="#e8e0d8"/>
        <circle cx="36" cy="17" r="3.5" fill="#222"/>
        <circle cx="37" cy="16.5" r="1" fill="#fff"/>
        <polygon points="32,22 40,24 32,26" fill="#8C3523"/>
        <path d="M14 36 Q4 30 8 44 Q14 48 20 42" fill="#e8e0d8"/>
        <path d="M50 36 Q60 30 56 44 Q50 48 44 42" fill="#e8e0d8"/>
      </svg>
      <p class="join-heading">Join the conversation</p>

      {#if !isLoggedIn}
        <p class="join-identity">
          You'll appear as <strong>{username}</strong>
          <button
            class="cycle-btn"
            class:spinning={isSpinning}
            on:click={cycleUsername}
            on:animationend={() => isSpinning = false}
            disabled={isCycling}
            aria-label="Get a different name"
            title="Try a different name"
          >↻</button>
        </p>
      {/if}

      <button class="join-btn" on:click={joinChat}>Join chat</button>
    </div>
  {:else}
    {#each messageGroups as group (group.key)}
      {#if group.type === 'system'}
        <div class="message system">
          <span class="message-text">{group.msg.text}</span>
        </div>
      {:else}
        <div class="message-group" class:me={group.is_me}>
          <div class="group-header">
            <div
              class="msg-thumb"
              class:clickable={group.is_account}
              on:mouseenter={(e) => { if (group.is_account) showUserPopup(group.user_id, group.username, e); }}
              on:mouseleave={() => { if (group.is_account) hideUserPopup(); }}
            >
              {#if group.avatar}
                <img src={group.avatar} alt={group.username} />
              {:else}
                <div class="msg-thumb-initial">{(group.username ?? '?').charAt(0).toUpperCase()}</div>
              {/if}
            </div>
            <span
              class="username"
              class:account-username={group.is_account}
              on:mouseenter={(e) => { if (group.is_account) showUserPopup(group.user_id, group.username, e); }}
              on:mouseleave={() => { if (group.is_account) hideUserPopup(); }}
            >{group.username}</span>
          </div>
          <div class="group-messages">
            {#each group.messages as msg (msg.timestamp)}
              <div class="msg-row">
                <span class="msg-time">
                  {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
                <span class="msg-text">{msg.text}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {/each}
    <div bind:this={messagesEndEl}></div>
  {/if}
</div>

{#if hasJoined}
  <div class="chat-identity">Chatting as <strong>{username}</strong></div>
  <form on:submit={handleSendMessage} class="message-form">
    <input
      type="text"
      bind:value={newMessage}
      placeholder="Type a message..."
      maxlength="255"
      autofocus
    />
    <button type="submit">Send</button>
  </form>
{/if}

{#if popup}
  <div
    class="user-popup"
    style="top: {popup.y}px; left: {popup.x}px"
    on:mouseenter={cancelHidePopup}
    on:mouseleave={hideUserPopup}
    role="tooltip"
  >
    {#if popup.profile === undefined}
      <p class="popup-loading">Loading…</p>
    {:else if popup.profile === null}
      <p class="popup-loading">Profile unavailable</p>
    {:else}
      {#if popup.profile.avatar}
        <img src={popup.profile.avatar} alt={popup.profile.username} class="popup-avatar-img" />
      {:else}
        <div class="popup-avatar-initial">{popup.profile.username.charAt(0).toUpperCase()}</div>
      {/if}
      <p class="popup-username">{popup.profile.username}</p>
      {#if popup.profile.bio}
        <p class="popup-bio">{popup.profile.bio}</p>
      {/if}
    {/if}
  </div>
{/if}
