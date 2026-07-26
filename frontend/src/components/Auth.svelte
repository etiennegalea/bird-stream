<script>
  import { createEventDispatcher } from 'svelte';
  import { auth } from '../stores/auth.js';
  import { getApiBaseUrl } from '../utils.js';

  /**
   * view: 'login' | 'signup' | 'forgot' | 'reset' | 'verify'
   * resetToken / verifyToken — populated from URL params when applicable.
   */
  export let view = 'login';
  export let resetToken = '';
  export let verifyToken = '';

  const dispatch = createEventDispatcher();

  let email = '';
  let loginIdentifier = '';
  let username = '';
  let password = '';
  let confirmPassword = '';
  let showPassword = false;
  let error = '';
  let info = '';
  let loading = false;

  // Run email verification automatically when the component mounts in verify mode.
  $: if (view === 'verify' && verifyToken) {
    runVerify();
  }

  async function api(path, body) {
    const resp = await fetch(`${getApiBaseUrl()}/auth/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    return { ok: resp.ok, status: resp.status, data };
  }

  function reset() {
    error = '';
    info = '';
    loading = false;
  }

  function switchTo(newView, keepEmail = false) {
    reset();
    if (!keepEmail) email = '';
    loginIdentifier = '';
    username = '';
    password = '';
    confirmPassword = '';
    showPassword = false;
    view = newView;
  }

  async function handleSignup() {
    error = '';
    if (password !== confirmPassword) { error = 'Passwords do not match'; return; }
    if (password.length < 8) { error = 'Password must be at least 8 characters'; return; }
    loading = true;
    const { ok, data } = await api('register', { email, username, password });
    loading = false;
    if (ok) {
      info = data.message || 'Check your inbox for a verification link.';
      email = username = password = confirmPassword = '';
    } else {
      error = data.detail || 'Registration failed';
    }
  }

  async function handleLogin() {
    error = '';
    loading = true;
    const { ok, status, data } = await api('login', { identifier: loginIdentifier, password });
    loading = false;
    if (ok) {
      auth.login(data.user, data.access_token);
      dispatch('authenticated', data.user);
    } else {
      error = status === 403
        ? data.detail + ' Check your inbox for the verification email.'
        : (data.detail || 'Login failed');
    }
  }

  async function handleForgot() {
    error = '';
    loading = true;
    const { ok, data } = await api('forgot-password', { email });
    loading = false;
    if (ok) {
      info = data.message;
    } else {
      error = data.detail || 'Something went wrong';
    }
  }

  async function handleReset() {
    error = '';
    if (password !== confirmPassword) { error = 'Passwords do not match'; return; }
    if (password.length < 8) { error = 'Password must be at least 8 characters'; return; }
    loading = true;
    const { ok, data } = await api('reset-password', { token: resetToken, password });
    loading = false;
    if (ok) {
      info = data.message;
      password = confirmPassword = '';
    } else {
      error = data.detail || 'Reset failed. The link may have expired.';
    }
  }

  async function runVerify() {
    info = '';
    error = '';
    loading = true;
    const { ok, data } = await api('verify-email', { token: verifyToken });
    loading = false;
    if (ok) {
      info = data.message;
    } else {
      error = data.detail || 'Verification failed. The link may have expired.';
    }
  }
</script>

<div class="auth-overlay" role="dialog" aria-modal="true">
  <div class="auth-card">
    <button class="close-btn" on:click={() => dispatch('close')} aria-label="Close">✕</button>

    {#if view === 'verify'}
      <h2>Email Verification</h2>
      {#if loading}<p class="muted">Verifying…</p>{/if}
      {#if info}<p class="success">{info} <button class="link-btn" on:click={() => switchTo('login')}>Log in</button></p>{/if}
      {#if error}<p class="error">{error}</p>{/if}

    {:else if view === 'login'}
      <h2>Log in</h2>
      {#if info}<p class="success">{info}</p>{/if}
      {#if error}<p class="error">{error}</p>{/if}
      <form on:submit|preventDefault={handleLogin}>
        <label>Email or username<input type="text" bind:value={loginIdentifier} required autocomplete="username" /></label>
        <label>
          Password
          <span class="password-field">
            <input type={showPassword ? 'text' : 'password'} value={password} on:input={(event) => password = event.currentTarget.value} required autocomplete="current-password" />
            <button
              type="button"
              class="password-toggle"
              on:click={() => showPassword = !showPassword}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
            >{showPassword ? 'Hide' : 'Show'}</button>
          </span>
        </label>
        <button type="submit" class="primary-btn" disabled={loading}>{loading ? 'Logging in…' : 'Log in'}</button>
      </form>
      <div class="auth-links">
        <button class="link-btn" on:click={() => switchTo('forgot', true)}>Forgot password?</button>
        <span class="sep">·</span>
        <button class="link-btn" on:click={() => switchTo('signup')}>Create account</button>
      </div>

    {:else if view === 'signup'}
      <h2>Create account</h2>
      {#if info}<p class="success">{info}</p>{/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if !info}
        <form on:submit|preventDefault={handleSignup}>
          <label>Email<input type="email" bind:value={email} required autocomplete="email" /></label>
          <label>Username<input type="text" bind:value={username} required minlength="2" maxlength="50" autocomplete="username" /></label>
          <label>
            Password
            <span class="password-field">
              <input type={showPassword ? 'text' : 'password'} value={password} on:input={(event) => password = event.currentTarget.value} required minlength="8" autocomplete="new-password" />
              <button
                type="button"
                class="password-toggle"
                on:click={() => showPassword = !showPassword}
                aria-label={showPassword ? 'Hide passwords' : 'Show passwords'}
                aria-pressed={showPassword}
              >{showPassword ? 'Hide' : 'Show'}</button>
            </span>
          </label>
          <label>Confirm password<input type={showPassword ? 'text' : 'password'} value={confirmPassword} on:input={(event) => confirmPassword = event.currentTarget.value} required minlength="8" autocomplete="new-password" /></label>
          <button type="submit" class="primary-btn" disabled={loading}>{loading ? 'Creating…' : 'Create account'}</button>
        </form>
      {/if}
      <div class="auth-links">
        <button class="link-btn" on:click={() => switchTo('login')}>Already have an account?</button>
      </div>

    {:else if view === 'forgot'}
      <h2>Reset password</h2>
      {#if info}<p class="success">{info}</p>{/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if !info}
        <form on:submit|preventDefault={handleForgot}>
          <label>Email<input type="email" bind:value={email} required autocomplete="email" /></label>
          <button type="submit" class="primary-btn" disabled={loading}>{loading ? 'Sending…' : 'Send reset link'}</button>
        </form>
      {/if}
      <div class="auth-links">
        <button class="link-btn" on:click={() => switchTo('login')}>Back to log in</button>
      </div>

    {:else if view === 'reset'}
      <h2>Set new password</h2>
      {#if info}<p class="success">{info} <button class="link-btn" on:click={() => switchTo('login')}>Log in</button></p>{/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if !info}
        <form on:submit|preventDefault={handleReset}>
          <label>
            New password
            <span class="password-field">
              <input type={showPassword ? 'text' : 'password'} value={password} on:input={(event) => password = event.currentTarget.value} required minlength="8" autocomplete="new-password" />
              <button
                type="button"
                class="password-toggle"
                on:click={() => showPassword = !showPassword}
                aria-label={showPassword ? 'Hide passwords' : 'Show passwords'}
                aria-pressed={showPassword}
              >{showPassword ? 'Hide' : 'Show'}</button>
            </span>
          </label>
          <label>Confirm password<input type={showPassword ? 'text' : 'password'} value={confirmPassword} on:input={(event) => confirmPassword = event.currentTarget.value} required minlength="8" autocomplete="new-password" /></label>
          <button type="submit" class="primary-btn" disabled={loading}>{loading ? 'Saving…' : 'Set password'}</button>
        </form>
      {/if}
    {/if}
  </div>
</div>

<style>
  .auth-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .auth-card {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 14px;
    padding: 2rem;
    width: 100%;
    max-width: 380px;
    position: relative;
    color: #333;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  }

  h2 {
    margin: 0 0 1.25rem;
    font-size: 1.3rem;
    color: #222;
    font-weight: 700;
  }

  .close-btn {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    background: none;
    border: none;
    color: #aaa;
    font-size: 1rem;
    cursor: pointer;
    padding: 0.25rem 0.5rem;
    border-radius: 6px;
    line-height: 1;
  }
  .close-btn:hover { color: #555; background: #f0f0f0; }

  form { display: flex; flex-direction: column; gap: 0.85rem; }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    font-size: 0.82rem;
    color: #777;
  }

  input {
    padding: 0.55rem 0.75rem;
    background: #fafafa;
    border: 1px solid #d0d0d0;
    border-radius: 8px;
    color: #333;
    font-size: 0.95rem;
    outline: none;
    font-family: inherit;
    transition: border-color 0.15s;
  }
  input:focus { border-color: #E87530; background: #fff; }

  .password-field {
    position: relative;
    display: flex;
  }

  .password-field input {
    width: 100%;
    padding-right: 3.75rem;
    box-sizing: border-box;
  }

  .password-toggle {
    position: absolute;
    top: 50%;
    right: 0.65rem;
    transform: translateY(-50%);
    padding: 0.2rem;
    background: none;
    border: none;
    color: #B35610;
    font: inherit;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
  }
  .password-toggle:hover { color: #8A3C06; }
  .password-toggle:focus-visible {
    outline: 2px solid #E87530;
    outline-offset: 2px;
    border-radius: 3px;
  }

  .primary-btn {
    margin-top: 0.25rem;
    padding: 0.65rem;
    background: #B35610;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }
  .primary-btn:hover:not(:disabled) { background: #8A3C06; }
  .primary-btn:disabled { opacity: 0.55; cursor: default; }

  .auth-links {
    margin-top: 1rem;
    display: flex;
    gap: 0.5rem;
    justify-content: center;
    font-size: 0.83rem;
    flex-wrap: wrap;
    color: #888;
  }

  .link-btn {
    background: none;
    border: none;
    color: #B35610;
    cursor: pointer;
    font-size: inherit;
    padding: 0;
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .link-btn:hover { color: #C96120; }

  .sep { color: #ccc; }

  .error { color: #dc2626; font-size: 0.88rem; margin: 0.4rem 0; }
  .success { color: #16a34a; font-size: 0.88rem; margin: 0.4rem 0; }
  .muted { color: #999; font-size: 0.88rem; }
</style>
