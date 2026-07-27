<script>
  import { createEventDispatcher, onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/AdminPanel.css';

  const dispatch = createEventDispatcher();

  let accounts = [];
  let guests = [];
  let blockedIps = [];
  let blockedUsers = [];
  let loading = true;
  let error = '';
  let pollTimer = null;

  function authHeader() {
    const token = get(auth)?.token;
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  async function fetchUsers() {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/admin/users`, { headers: authHeader() });
      if (resp.ok) {
        const data = await resp.json();
        accounts = data.accounts ?? [];
        guests = data.guests ?? [];
        blockedIps = data.blocked_ips ?? [];
        blockedUsers = data.blocked_users ?? [];
        error = '';
      } else {
        error = resp.status === 403 ? 'Admin access required' : 'Failed to load users';
      }
    } catch {
      error = 'Network error';
    } finally {
      loading = false;
    }
  }

  async function blockIp(ip) {
    if (!ip) return;
    await fetch(`${getApiBaseUrl()}/admin/block-ip`, {
      method: 'POST',
      headers: authHeader(),
      body: JSON.stringify({ ip }),
    });
    await fetchUsers();
  }

  async function unblockIp(ip) {
    await fetch(`${getApiBaseUrl()}/admin/unblock-ip`, {
      method: 'POST',
      headers: authHeader(),
      body: JSON.stringify({ ip }),
    });
    await fetchUsers();
  }

  async function setUserBlocked(userId, isBlocked) {
    await fetch(`${getApiBaseUrl()}/admin/users/${userId}/blocked`, {
      method: 'POST',
      headers: authHeader(),
      body: JSON.stringify({ is_blocked: isBlocked }),
    });
    await fetchUsers();
  }

  onMount(() => {
    fetchUsers();
    pollTimer = setInterval(fetchUsers, 5000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });
</script>

<div class="admin-drawer" role="complementary" aria-label="Admin panel">
  <div class="admin-drawer-header">
    <div class="admin-drawer-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/>
      </svg>
      ADMIN PANEL
    </div>
    <button class="admin-close-btn" on:click={() => dispatch('close')} aria-label="Close admin panel">✕</button>
  </div>

  <div class="admin-drawer-body">
    {#if error}
      <p class="admin-error">{error}</p>
    {:else if loading}
      <p class="admin-empty">Loading…</p>
    {:else}

      <!-- Registered Users -->
      <div class="admin-group">
        <div class="admin-group-label">
          Users
          <span class="admin-count-badge">{accounts.length}</span>
        </div>
        {#if accounts.length === 0}
          <p class="admin-empty">No registered users in chat</p>
        {:else}
          {#each accounts as user}
            <div class="admin-user-row">
              {#if user.avatar}
                <img src={user.avatar} alt={user.username} class="admin-avatar" />
              {:else}
                <div class="admin-avatar-placeholder">
                  {user.username.charAt(0).toUpperCase()}
                </div>
              {/if}
              <div class="admin-user-info">
                <div class="admin-username">
                  {user.username}
                  {#if user.watching_stream}
                    <span class="admin-stream-dot" title="Watching stream"></span>
                  {/if}
                </div>
                {#if user.email}
                  <div class="admin-email">{user.email}</div>
                {/if}
                <div class="admin-ip" title="Current public IP">
                  {user.chat_ip ?? '—'}
                  {#if user.last_ip && user.last_ip !== user.chat_ip}
                    <span title="Last login public IP"> / {user.last_ip}</span>
                  {/if}
                </div>
              </div>
              <button
                class="admin-block-btn"
                disabled={!user.user_id}
                on:click={() => setUserBlocked(user.user_id, true)}
                title={`Block ${user.username}'s account`}
              >
                BLOCK
              </button>
            </div>
          {/each}
        {/if}
      </div>

      <div class="admin-divider"></div>

      <!-- Guests -->
      <div class="admin-group">
        <div class="admin-group-label">
          Guests
          <span class="admin-count-badge">{guests.length}</span>
        </div>
        {#if guests.length === 0}
          <p class="admin-empty">No guests in chat</p>
        {:else}
          {#each guests as guest}
            <div class="admin-user-row">
              <div class="admin-avatar-guest">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 12c2.761 0 5-2.239 5-5s-2.239-5-5-5-5 2.239-5 5 2.239 5 5 5zm0 2c-3.332 0-10 1.667-10 5v1h20v-1c0-3.333-6.668-5-10-5z"/>
                </svg>
              </div>
              <div class="admin-user-info">
                <div class="admin-username">{guest.username}</div>
                <div class="admin-ip">{guest.ip ?? '—'}</div>
              </div>
              <button
                class="admin-block-btn"
                disabled={!guest.ip}
                on:click={() => blockIp(guest.ip)}
                title={guest.ip ? `Block ${guest.ip}` : 'No IP available'}
              >
                BLOCK
              </button>
            </div>
          {/each}
        {/if}
      </div>

      {#if blockedUsers.length > 0}
        <div class="admin-divider"></div>
        <div class="admin-group">
          <div class="admin-group-label">
            Blocked users
            <span class="admin-count-badge">{blockedUsers.length}</span>
          </div>
          {#each blockedUsers as user}
            <div class="admin-blocked-row">
              <span class="admin-blocked-ip">
                {user.username}
                {#if user.last_ip}<small>{user.last_ip}</small>{/if}
              </span>
              <button
                class="admin-unblock-btn"
                on:click={() => setUserBlocked(user.user_id, false)}
              >UNBLOCK</button>
            </div>
          {/each}
        </div>
      {/if}

      {#if blockedIps.length > 0}
        <div class="admin-divider"></div>

        <!-- Blocked IPs -->
        <div class="admin-group">
          <div class="admin-group-label">
            Blocked IPs
            <span class="admin-count-badge">{blockedIps.length}</span>
          </div>
          {#each blockedIps as ip}
            <div class="admin-blocked-row">
              <span class="admin-blocked-ip">{ip}</span>
              <button class="admin-unblock-btn" on:click={() => unblockIp(ip)}>UNBLOCK</button>
            </div>
          {/each}
        </div>
      {/if}

    {/if}
  </div>

  <div class="admin-refresh-row">
    <span class="admin-refresh-label">Auto-refreshes every 5s</span>
  </div>
</div>
