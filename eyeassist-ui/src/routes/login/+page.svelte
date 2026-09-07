<script lang="ts">
  import { goto } from '$app/navigation';
  import Button from '$lib/components/common/Button.svelte';
  import { login } from '$lib/api/auth';
  import { session } from '$lib/session';

  let email = '';
  let password = '';
  let error = '';
  let loading = false;

  async function submit() {
    loading = true;
    error = '';
    try {
      const user = await login(email, password);
      session.set(user);
      await goto('/consultation');
    } catch {
      error = 'Invalid email or password.';
    } finally {
      loading = false;
    }
  }
</script>

<section class="login">
  <form class="panel" on:submit|preventDefault={submit}>
    <img src="/eyeassist-wordmark.svg" alt="EyeAssist" />
    <h1>Clinical sign in</h1>
    <label>
      Email
      <input autocomplete="username" bind:value={email} required type="email" />
    </label>
    <label>
      Password
      <input autocomplete="current-password" bind:value={password} required type="password" />
    </label>
    {#if error}
      <p role="alert">{error}</p>
    {/if}
    <Button type="submit" disabled={loading}>{loading ? 'Signing in' : 'Sign in'}</Button>
  </form>
</section>

<style>
  .login {
    display: grid;
    min-height: calc(100vh - 128px);
    place-items: center;
  }

  form {
    display: grid;
    gap: var(--space-4);
    max-width: 420px;
    padding: var(--space-6);
    width: 100%;
  }

  img {
    height: 36px;
    width: 179px;
  }

  h1 {
    font-size: 1.55rem;
    margin: 0;
  }

  label {
    display: grid;
    font-weight: 700;
    gap: var(--space-2);
  }

  input {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    min-height: 42px;
    padding: 0 var(--space-3);
  }

  p {
    color: var(--danger);
    margin: 0;
  }
</style>
