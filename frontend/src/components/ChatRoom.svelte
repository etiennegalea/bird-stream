<script>
  import { onMount, onDestroy, tick } from 'svelte';
  import { get } from 'svelte/store';
  import '../styles/ChatRoom.css';
  import { auth } from '../stores/auth.js';
  import { formatChatTime } from '../chatTime.js';
  import { censorProfanity } from '../profanity.js';
  import { getApiBaseUrl, generateBirdUsername } from '../utils.js';

  export let onNewMessage = () => {};
  export let isChatVisible = true;
  export let onSignInClick = () => {};
  export let autoJoin = false;

  const authState = get(auth);
  const isLoggedIn = !!authState?.user?.username;
  const isAdmin = !!authState?.user?.is_admin;
  $: profanityFilterEnabled = $auth?.user?.profanity_filter_enabled ?? true;

  let username = authState?.user?.username ?? generateBirdUsername();
  let messages = [];
  let newMessage = '';
  let ws = null;
  let messagesEndEl;
  let hasJoined = false;
  let autoJoinAttempted = false;
  let isCycling = false;
  let isSpinning = false;
  let messageMenu = null;
  let longPressTimer = null;
  let suppressNextWindowClick = false;

  function portal(node) {
    document.body.appendChild(node);
    return {
      destroy() {
        if (node.parentNode) node.parentNode.removeChild(node);
      }
    };
  }

  // Participant list
  let participants = { count: 0, accounts: [], guests: [] };
  let showParticipantList = false;
  let participantPopupPos = { x: 0, y: 0 };

  function openParticipants(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const popupWidth = 220;
    const x = Math.max(8, rect.right - popupWidth);
    participantPopupPos = { x, y: rect.bottom + 6 };
    showParticipantList = true;
  }

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

      if (data.type === 'participants') {
        participants = data;
        return;
      }

      if (data.type === 'message' && data.timestamp) {
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
      }

      if (data.type === 'history') {
        messages = data.messages.filter(msg => msg.type !== 'system');
      } else if (data.type === 'message') {
        // Profanity counts are live data. Drop both filter-mode cache entries
        // so the sender's next hover includes this message (including our own).
        const senderProfileKey = data.user_id != null ? data.user_id : `u:${data.username}`;
        delete profileCache[`${senderProfileKey}|filter:true`];
        delete profileCache[`${senderProfileKey}|filter:false`];
        messages = [...messages, data];
        onNewMessage(data);
      } else if (data.type === 'message_deleted') {
        messages = messages.filter(message => message.id !== data.message_id);
        if (data.user_id != null) {
          delete profileCache[`${data.user_id}|filter:true`];
          delete profileCache[`${data.user_id}|filter:false`];
        }
        if (messageMenu?.message?.id === data.message_id) messageMenu = null;
      } else if (data.type === 'system') {
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
    const popupHeight = 260;
    const spaceRight = window.innerWidth - rect.right - 10;
    const x = spaceRight >= popupWidth ? rect.right + 6 : rect.left - popupWidth - 6;
    const y = Math.max(8, Math.min(rect.top - 8, window.innerHeight - popupHeight));

    const profileKey = userId != null ? userId : `u:${hovUsername}`;
    const cacheKey = `${profileKey}|filter:${profanityFilterEnabled}`;
    popup = { cacheKey, x, y, profile: cacheKey in profileCache ? profileCache[cacheKey] : undefined };

    // When the viewer has filtering off, counts can change with every message;
    // refresh on every hover instead of serving an indefinitely stale record.
    if (!(cacheKey in profileCache) || !profanityFilterEnabled) {
      try {
        const url = userId != null
          ? `${getApiBaseUrl()}/auth/profile/public/id/${userId}`
          : `${getApiBaseUrl()}/auth/profile/public/${encodeURIComponent(hovUsername)}`;
        const resp = await fetch(url, {
          headers: authState?.token ? { Authorization: `Bearer ${authState.token}` } : {},
        });
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

  $: if (isLoggedIn && autoJoin && !hasJoined && !autoJoinAttempted) {
    autoJoinAttempted = true;
    joinChat();
  }

  $: {
    // Track only these three; popup changes won't trigger scroll
    void messages; void hasJoined; void isChatVisible;
    tick().then(() => {
      if (hasJoined && isChatVisible && messagesEndEl) {
        messagesEndEl.scrollIntoView({ behavior: 'smooth' });
      }
    });
  }

  function handleSendMessage(e) {
    e.preventDefault();
    if (!newMessage.trim() || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ username, text: newMessage, timestamp: new Date().toISOString() }));
    newMessage = '';
  }

  function openMessageMenu(message, group, x, y) {
    if (!isAdmin || message.id == null) return;
    const menuWidth = 180;
    const menuHeight = 92;
    messageMenu = {
      message,
      group,
      x: Math.max(8, Math.min(x, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(y, window.innerHeight - menuHeight - 8)),
      loading: false,
      error: '',
    };
  }

  function openDesktopMessageMenu(event, message, group) {
    const rect = event.currentTarget.getBoundingClientRect();
    openMessageMenu(message, group, rect.right - 180, rect.bottom + 4);
  }

  function startLongPress(event, message, group) {
    if (!isAdmin || message.id == null) return;
    cancelLongPress();
    const touch = event.touches?.[0];
    if (!touch) return;
    const { clientX, clientY } = touch;
    longPressTimer = setTimeout(() => {
      openMessageMenu(message, group, clientX, clientY);
      suppressNextWindowClick = true;
      navigator.vibrate?.(30);
      longPressTimer = null;
    }, 550);
  }

  function cancelLongPress() {
    if (longPressTimer) clearTimeout(longPressTimer);
    longPressTimer = null;
  }

  function handleWindowClick() {
    if (suppressNextWindowClick) {
      suppressNextWindowClick = false;
      return;
    }
    messageMenu = null;
  }

  async function deleteSelectedMessage() {
    if (!messageMenu || messageMenu.loading) return;
    messageMenu = { ...messageMenu, loading: true, error: '' };
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/chat/messages/${messageMenu.message.id}`,
        { method: 'DELETE', headers: { Authorization: `Bearer ${authState.token}` } },
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        messageMenu = { ...messageMenu, loading: false, error: data.detail || 'Could not delete message.' };
        return;
      }
      messages = messages.filter(message => message.id !== data.message_id);
      messageMenu = null;
    } catch {
      messageMenu = { ...messageMenu, loading: false, error: 'Network error.' };
    }
  }

  async function blockSelectedUser() {
    if (!messageMenu?.group?.user_id || messageMenu.loading) return;
    messageMenu = { ...messageMenu, loading: true, error: '' };
    try {
      const resp = await fetch(
        `${getApiBaseUrl()}/admin/users/${messageMenu.group.user_id}/blocked`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${authState.token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ is_blocked: true }),
        },
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        messageMenu = { ...messageMenu, loading: false, error: data.detail || 'Could not block user.' };
        return;
      }
      messageMenu = null;
    } catch {
      messageMenu = { ...messageMenu, loading: false, error: 'Network error.' };
    }
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
    cancelLongPress();
  });
</script>

<svelte:window on:click={handleWindowClick} />

{#if hasJoined}
  <div class="chat-bar">
    <div
      class="participant-pill"
      on:mouseenter={openParticipants}
      on:mouseleave={() => showParticipantList = false}
      role="button"
      tabindex="0"
      aria-label="Chat participants"
    >
      <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path d="M9 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM17 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 0 0-1.5-4.33A5 5 0 0 1 19 16v1h-6.07zM6 11a5 5 0 0 1 5 5v1H1v-1a5 5 0 0 1 5-5z"/>
      </svg>
      {participants.count}
    </div>
  </div>
{/if}

<div class="chat-messages">
  {#if !hasJoined}
    <div class="join-prompt">
      <img class="join-bird-icon" src="/singing-bird.svg" alt="Singing birb icon" />
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
            {#each group.messages as msg, i (msg.id ?? msg.timestamp)}
              {@const timeStr = formatChatTime(msg.timestamp)}
              {@const prevTimeStr = i > 0 ? formatChatTime(group.messages[i - 1].timestamp) : null}
              <div
                class="msg-row"
                class:admin-message={isAdmin}
                class:gap-above={i > 0 && timeStr !== prevTimeStr}
                on:touchstart={(event) => startLongPress(event, msg, group)}
                on:touchend={cancelLongPress}
                on:touchcancel={cancelLongPress}
                on:touchmove={cancelLongPress}
              >
                <span class="msg-time">{timeStr !== prevTimeStr ? timeStr : ''}</span>
                <span class="msg-text">{profanityFilterEnabled ? censorProfanity(msg.text) : msg.text}</span>
                {#if isAdmin && msg.id != null}
                  <button
                    class="message-admin-trigger"
                    type="button"
                    aria-label="Moderate message"
                    title="Message actions"
                    on:click|stopPropagation={(event) => openDesktopMessageMenu(event, msg, group)}
                  >•••</button>
                {/if}
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
  {#if isLoggedIn}
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
  {:else}
    <div class="read-only-notice">
      <span>Observing as <strong>{username}</strong></span>
      <span class="read-only-hint">
      <button class="sign-in-link" on:click={onSignInClick}>Log in</button> to participate
    </span>
    </div>
  {/if}
{/if}

{#if messageMenu}
  <div
    use:portal
    class="message-admin-menu"
    style="left: {messageMenu.x}px; top: {messageMenu.y}px"
    role="menu"
    tabindex="-1"
    on:click|stopPropagation
    on:keydown|stopPropagation
  >
    <button role="menuitem" disabled={messageMenu.loading} on:click={deleteSelectedMessage}>
      Delete message
    </button>
    <button
      role="menuitem"
      disabled={messageMenu.loading || !messageMenu.group.user_id || messageMenu.group.user_id === authState.user.id}
      on:click={blockSelectedUser}
    >Block user</button>
    {#if messageMenu.error}<p role="alert">{messageMenu.error}</p>{/if}
  </div>
{/if}

{#if showParticipantList && participants.count > 0}
  <div
    use:portal
    class="participant-popup"
    style="top: {participantPopupPos.y}px; left: {participantPopupPos.x}px"
    on:mouseenter={() => showParticipantList = true}
    on:mouseleave={() => showParticipantList = false}
    role="tooltip"
  >
    {#if participants.accounts.length > 0}
      <div class="pp-section pp-section-members">
        <span class="pp-section-dot"></span>
        Members ({participants.accounts.length})
      </div>
      {#each participants.accounts as name}
        <div class="pp-entry pp-account">{name}</div>
      {/each}
    {/if}
    {#if participants.guests.length > 0}
      <div class="pp-section pp-section-guests">
        <span class="pp-section-dot"></span>
        Guests ({participants.guests.length})
      </div>
      {#each participants.guests as name}
        <div class="pp-entry">{name}</div>
      {/each}
    {/if}
  </div>
{/if}

{#if popup}
  <div
    use:portal
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
      <div class="popup-img-col">
        {#if popup.profile.avatar}
          <img src={popup.profile.avatar} alt={popup.profile.username} class="popup-avatar-img" />
        {:else}
          <div class="popup-avatar-initial">{popup.profile.username.charAt(0).toUpperCase()}</div>
        {/if}
      </div>
      <div class="popup-text-col">
        <p class="popup-username">{popup.profile.username}</p>
        {#if popup.profile.bio}
          <p class="popup-bio">{popup.profile.bio}</p>
        {/if}
        {#if popup.profile.can_view_profanities}
          <div class="popup-profanities" aria-label="Recent profanity use">
            <span>{popup.profile.profanity_retention_days ?? 7}-day profanity</span>
            {#if popup.profile.profanities?.length}
              <ul>
                {#each popup.profile.profanities as profanity}
                  <li><span>{profanity.word}</span><strong>×{profanity.count}</strong></li>
                {/each}
              </ul>
            {:else}
              <p class="popup-profanities-empty">None recorded</p>
            {/if}
            <div class="popup-deleted-count">
              <span>Deleted messages (all time)</span>
              <strong>×{popup.profile.deleted_message_count ?? 0}</strong>
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}
