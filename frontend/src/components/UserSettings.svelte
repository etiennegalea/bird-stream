<script>
  import { createEventDispatcher, onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { readAppearance, saveAppearance } from '../appearance.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/UserSettings.css';

  const dispatch = createEventDispatcher();
  const authState = get(auth);
  const token = authState?.token;
  const isAdmin = authState?.user?.is_admin ?? false;
  const sections = [
    ['profile', 'Profile'],
    ['account', 'Account'],
    ['options', 'Options'],
    ['appearance', 'Appearance'],
  ];
  const accentColours = ['#B35610', '#2563EB', '#7C3AED', '#DB2777', '#059669', '#DC2626'];

  let activeSection = 'profile';
  let email = '';
  let username = authState?.user?.username ?? '';
  let bio = '';
  let avatarDataUrl = null;
  let avatarFile = null;
  let currentPassword = '';
  let newPassword = '';
  let confirmPassword = '';
  let birdNotificationEmail = false;
  let autoJoinChat = false;
  let profanityFilterEnabled = true;
  let showDeleteConfirmation = false;
  let deletePassword = '';
  let message = '';
  let error = '';
  let loading = false;
  let appearance = readAppearance();

  function authHeader() {
    return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  onMount(async () => {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        email = data.email ?? '';
        username = data.username ?? username;
        bio = data.bio ?? '';
        avatarDataUrl = data.avatar ?? null;
        birdNotificationEmail = data.bird_notification_email ?? false;
        autoJoinChat = data.auto_join_chat ?? false;
        profanityFilterEnabled = data.profanity_filter_enabled ?? true;
      }
    } catch {
      error = 'Could not load your settings.';
    }
  });

  function selectSection(section) {
    activeSection = section;
    message = '';
    error = '';
  }

  function resizeImage(file, maxPx = 150) {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(maxPx / img.width, maxPx / img.height, 1);
          const canvas = document.createElement('canvas');
          canvas.width = Math.round(img.width * scale);
          canvas.height = Math.round(img.height * scale);
          canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        img.src = event.target.result;
      };
      reader.readAsDataURL(file);
    });
  }

  async function handleAvatarChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    avatarDataUrl = await resizeImage(file);
    avatarFile = file;
  }

  async function updateProfile(body, successMessage) {
    error = '';
    message = '';
    loading = true;
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
        method: 'PATCH',
        headers: authHeader(),
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        error = data.detail || 'Could not save your changes.';
        return false;
      }
      email = data.email;
      username = data.username;
      bio = data.bio ?? '';
      avatarDataUrl = data.avatar ?? null;
      birdNotificationEmail = data.bird_notification_email ?? false;
      autoJoinChat = data.auto_join_chat ?? false;
      profanityFilterEnabled = data.profanity_filter_enabled ?? true;
      auth.updateUser({
        email: data.email,
        username: data.username,
        avatar: data.avatar,
        bio: data.bio,
        bird_notification_email: data.bird_notification_email,
        auto_join_chat: data.auto_join_chat,
        profanity_filter_enabled: data.profanity_filter_enabled,
      });
      message = successMessage;
      return true;
    } catch {
      error = 'Network error. Please try again.';
      return false;
    } finally {
      loading = false;
    }
  }

  async function saveProfile() {
    const body = { bio };
    if (avatarFile) body.avatar = avatarDataUrl;
    if (await updateProfile(body, 'Profile saved.')) avatarFile = null;
  }

  async function saveAccount() {
    await updateProfile({ email, username }, 'Account details saved.');
  }

  async function saveOptions() {
    await updateProfile(
      {
        bird_notification_email: birdNotificationEmail,
        auto_join_chat: autoJoinChat,
        profanity_filter_enabled: profanityFilterEnabled,
      },
      'Options saved.',
    );
  }

  async function changePassword() {
    error = '';
    message = '';
    if (newPassword !== confirmPassword) {
      error = 'Passwords do not match.';
      return;
    }
    if (newPassword.length < 8) {
      error = 'New password must be at least 8 characters.';
      return;
    }
    loading = true;
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/change-password`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        error = data.detail || 'Could not change your password.';
      } else {
        currentPassword = '';
        newPassword = '';
        confirmPassword = '';
        message = 'Password changed.';
      }
    } catch {
      error = 'Network error. Please try again.';
    } finally {
      loading = false;
    }
  }

  function cancelDeleteAccount() {
    showDeleteConfirmation = false;
    deletePassword = '';
    error = '';
  }

  async function deleteAccount() {
    error = '';
    message = '';
    loading = true;
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/account`, {
        method: 'DELETE',
        headers: authHeader(),
        body: JSON.stringify({ current_password: deletePassword }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        error = data.detail || 'Could not delete your account.';
        return;
      }

      auth.logout();
      dispatch('close');
      window.location.reload();
    } catch {
      error = 'Network error. Please try again.';
    } finally {
      loading = false;
    }
  }

  function updateAppearance(patch) {
    appearance = { ...appearance, ...patch };
    saveAppearance(appearance);
  }
</script>

<div class="settings-overlay" role="presentation" on:click|self={() => dispatch('close')}>
  <div class="settings-card" role="dialog" aria-modal="true" aria-labelledby="settings-title">
    <header class="settings-header">
      <div class="settings-title-row">
        <h2 id="settings-title">User settings</h2>
        {#if isAdmin}<span class="admin-tag">ADMIN</span>{/if}
      </div>
      <button class="close-btn" on:click={() => dispatch('close')} aria-label="Close settings">✕</button>
    </header>

    <div class="settings-layout">
      <nav class="settings-menu" aria-label="Settings sections">
        {#each sections as section}
          <button
            class:active={activeSection === section[0]}
            aria-current={activeSection === section[0] ? 'page' : undefined}
            on:click={() => selectSection(section[0])}
          >{section[1]}</button>
        {/each}
      </nav>

      <main class="settings-content">
        <div class="section-heading">
          <h3>{sections.find(section => section[0] === activeSection)?.[1]}</h3>
        </div>
        {#if message}<p class="success" role="status">{message}</p>{/if}
        {#if error}<p class="error" role="alert">{error}</p>{/if}

        {#if activeSection === 'profile'}
          <div class="avatar-section">
            <label class="avatar-wrap" aria-label="Change profile picture">
              {#if avatarDataUrl}
                <img src={avatarDataUrl} alt="Profile" class="avatar-img" />
              {:else}
                <span class="avatar-placeholder">{username.charAt(0).toUpperCase()}</span>
              {/if}
              <span class="avatar-overlay">Change</span>
              <input type="file" accept="image/*" class="avatar-input" on:change={handleAvatarChange} />
            </label>
          </div>
          <form class="settings-form" on:submit|preventDefault={saveProfile}>
            <label>Bio
              <textarea bind:value={bio} maxlength="500" rows="5" placeholder="Tell us about yourself…"></textarea>
              <span class="char-count">{bio.length}/500</span>
            </label>
            <button class="primary-btn" type="submit" disabled={loading}>
              {loading ? 'Saving…' : 'Save profile'}
            </button>
          </form>
        {:else if activeSection === 'account'}
          <form class="settings-form" on:submit|preventDefault={saveAccount}>
            <label>Email
              <input type="email" bind:value={email} required autocomplete="email" />
            </label>
            <label>Username
              <input type="text" bind:value={username} minlength="2" maxlength="50" required autocomplete="username" />
            </label>
            <button class="primary-btn" type="submit" disabled={loading}>
              {loading ? 'Saving…' : 'Save account details'}
            </button>
          </form>
          <div class="divider"><span>Update password</span></div>
          <form class="settings-form" on:submit|preventDefault={changePassword}>
            <label>Current password
              <input type="password" bind:value={currentPassword} required autocomplete="current-password" />
            </label>
            <label>New password
              <input type="password" bind:value={newPassword} minlength="8" required autocomplete="new-password" />
            </label>
            <label>Confirm new password
              <input type="password" bind:value={confirmPassword} minlength="8" required autocomplete="new-password" />
            </label>
            <button class="primary-btn" type="submit" disabled={loading}>
              {loading ? 'Saving…' : 'Change password'}
            </button>
          </form>
          <div class="divider"><span>Danger zone</span></div>
          <section class="danger-zone" aria-labelledby="delete-account-title">
            <div>
              <h4 id="delete-account-title">Delete account</h4>
              <p>Permanently remove your profile and sign-in details. This cannot be undone.</p>
            </div>
            {#if showDeleteConfirmation}
              <form class="delete-account-form" on:submit|preventDefault={deleteAccount}>
                <label>Enter your current password to confirm
                  <input
                    type="password"
                    bind:value={deletePassword}
                    required
                    autocomplete="current-password"
                  />
                </label>
                <div class="danger-actions">
                  <button class="secondary-btn" type="button" disabled={loading} on:click={cancelDeleteAccount}>
                    Cancel
                  </button>
                  <button class="danger-btn" type="submit" disabled={loading || !deletePassword}>
                    {loading ? 'Deleting…' : 'Permanently delete account'}
                  </button>
                </div>
              </form>
            {:else}
              <button class="danger-btn" type="button" on:click={() => { showDeleteConfirmation = true; error = ''; message = ''; }}>
                Delete account
              </button>
            {/if}
          </section>
        {:else if activeSection === 'options'}
          <form class="settings-form" on:submit|preventDefault={saveOptions}>
            <label class="preference-card">
              <input type="checkbox" bind:checked={birdNotificationEmail} />
              <span>
                <strong>Email me when a bird is visible</strong>
                <small>Receive a snapshot from the main camera when Bird Stream detects a bird.</small>
              </span>
            </label>
            <p class="preference-note">Notifications are off by default. We’ll limit alerts so a visiting bird doesn’t fill your inbox.</p>
            <label class="preference-card">
              <input type="checkbox" bind:checked={autoJoinChat} />
              <span>
                <strong>Automatically join chat</strong>
                <small>Join the conversation with your account whenever you open Bird Stream while logged in.</small>
              </span>
            </label>
            <label class="preference-card">
              <input type="checkbox" bind:checked={profanityFilterEnabled} />
              <span>
                <strong>Filter profanities</strong>
                <small>Mask English and Maltese profanity in chat on this account. This is on by default.</small>
              </span>
            </label>
            <button class="primary-btn" type="submit" disabled={loading}>
              {loading ? 'Saving…' : 'Save options'}
            </button>
          </form>
        {:else}
          <fieldset class="appearance-group">
            <legend>Colour mode</legend>
            <div class="mode-grid">
              {#each ['light', 'dark', 'system'] as mode}
                <button
                  class:active={appearance.mode === mode}
                  on:click={() => updateAppearance({ mode })}
                >{mode.charAt(0).toUpperCase() + mode.slice(1)}</button>
              {/each}
            </div>
          </fieldset>
          <fieldset class="appearance-group">
            <legend>Accent colour</legend>
            <div class="accent-grid">
              {#each accentColours as colour}
                <button
                  class="accent-swatch"
                  class:active={appearance.accent === colour}
                  style={`--swatch: ${colour}`}
                  aria-label={`Use accent colour ${colour}`}
                  on:click={() => updateAppearance({ accent: colour })}
                ></button>
              {/each}
            </div>
          </fieldset>
        {/if}
      </main>
    </div>
  </div>
</div>
