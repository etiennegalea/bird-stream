<script>
  import { createEventDispatcher, onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl } from '../utils.js';
  import '../styles/UserSettings.css';

  const dispatch = createEventDispatcher();

  const authState = get(auth);
  const token = authState?.token;

  // Profile fields
  let username = authState?.user?.username ?? '';
  let bio = '';
  let avatarDataUrl = null;    // current preview (may differ from saved)
  let avatarFile = null;

  // Password fields
  let currentPassword = '';
  let newPassword = '';
  let confirmPassword = '';

  // UI state
  let profileError = '';
  let profileInfo = '';
  let profileLoading = false;
  let passwordError = '';
  let passwordInfo = '';
  let passwordLoading = false;

  function authHeader() {
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  onMount(async () => {
    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        username = data.username ?? username;
        bio = data.bio ?? '';
        avatarDataUrl = data.avatar ?? null;
      }
    } catch (err) {
      console.warn('Could not load profile:', err);
    }
  });

  function resizeImage(file, maxPx = 150) {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(maxPx / img.width, maxPx / img.height, 1);
          const canvas = document.createElement('canvas');
          canvas.width = Math.round(img.width * scale);
          canvas.height = Math.round(img.height * scale);
          canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    });
  }

  async function handleAvatarChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    avatarDataUrl = await resizeImage(file);
    avatarFile = file;
  }

  async function handleSaveProfile() {
    profileError = '';
    profileInfo = '';
    profileLoading = true;

    const body = { username, bio };
    if (avatarFile) body.avatar = avatarDataUrl;

    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/profile`, {
        method: 'PATCH',
        headers: authHeader(),
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        auth.updateUser({ username: data.username, avatar: data.avatar, bio: data.bio });
        avatarFile = null;
        profileInfo = 'Profile saved.';
      } else {
        profileError = data.detail || 'Failed to save profile.';
      }
    } catch (err) {
      profileError = 'Network error. Please try again.';
    } finally {
      profileLoading = false;
    }
  }

  async function handleChangePassword() {
    passwordError = '';
    passwordInfo = '';
    if (newPassword !== confirmPassword) { passwordError = 'Passwords do not match.'; return; }
    if (newPassword.length < 8) { passwordError = 'New password must be at least 8 characters.'; return; }
    passwordLoading = true;

    try {
      const resp = await fetch(`${getApiBaseUrl()}/auth/change-password`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        currentPassword = newPassword = confirmPassword = '';
        passwordInfo = 'Password changed.';
      } else {
        passwordError = data.detail || 'Failed to change password.';
      }
    } catch (err) {
      passwordError = 'Network error. Please try again.';
    } finally {
      passwordLoading = false;
    }
  }
</script>

<div class="settings-overlay" role="dialog" aria-modal="true">
  <div class="settings-card">
    <div class="settings-header">
      <h2>Account Settings</h2>
      <button class="close-btn" on:click={() => dispatch('close')} aria-label="Close">✕</button>
    </div>
    <div class="settings-body">

    <!-- Avatar -->
    <div class="avatar-section">
      <label class="avatar-wrap" aria-label="Change profile picture">
        {#if avatarDataUrl}
          <img src={avatarDataUrl} alt="Profile" class="avatar-img" />
        {:else}
          <div class="avatar-placeholder">{username.charAt(0).toUpperCase()}</div>
        {/if}
        <div class="avatar-overlay">Change</div>
        <input type="file" accept="image/*" class="avatar-input" on:change={handleAvatarChange} />
      </label>
    </div>

    <!-- Profile form -->
    <form on:submit|preventDefault={handleSaveProfile} class="settings-form">
      {#if profileInfo}<p class="success">{profileInfo}</p>{/if}
      {#if profileError}<p class="error">{profileError}</p>{/if}

      <label>
        Username
        <input type="text" bind:value={username} minlength="2" maxlength="50" required />
      </label>

      <label>
        Bio
        <textarea bind:value={bio} maxlength="500" rows="3" placeholder="Tell us about yourself…"></textarea>
        <span class="char-count">{bio.length}/500</span>
      </label>

      <button type="submit" class="primary-btn" disabled={profileLoading}>
        {profileLoading ? 'Saving…' : 'Save Profile'}
      </button>
    </form>

    <div class="divider"><span>Change Password</span></div>

    <!-- Password form -->
    <form on:submit|preventDefault={handleChangePassword} class="settings-form">
      {#if passwordInfo}<p class="success">{passwordInfo}</p>{/if}
      {#if passwordError}<p class="error">{passwordError}</p>{/if}

      <label>
        Current password
        <input type="password" bind:value={currentPassword} required autocomplete="current-password" />
      </label>
      <label>
        New password
        <input type="password" bind:value={newPassword} minlength="8" required autocomplete="new-password" />
      </label>
      <label>
        Confirm new password
        <input type="password" bind:value={confirmPassword} minlength="8" required autocomplete="new-password" />
      </label>

      <button type="submit" class="primary-btn" disabled={passwordLoading}>
        {passwordLoading ? 'Saving…' : 'Change Password'}
      </button>
    </form>

    </div>
  </div>
</div>
