<script lang="ts">
  import { goto } from '$app/navigation';
  import { session } from '$lib/session';
  import { logout } from '$lib/api/auth';

  async function signOut() {
    await logout();
    session.set(null);
    await goto('/login');
  }
</script>

<div class="shell">
  <header>
    <a class="brand" href="/consultation" aria-label="EyeAssist consultation">
      <img src="/eyeassist-wordmark.svg" alt="EyeAssist" />
    </a>
    <nav aria-label="Primary">
      <a href="/consultation">Consultation</a>
      {#if $session?.role === 'admin'}
        <a href="/admin/health">System Health</a>
      {/if}
    </nav>
    {#if $session}
      <div class="user">
        <span>{$session.name}</span>
        <button on:click={signOut}>Sign out</button>
      </div>
    {/if}
  </header>
  <main>
    <slot />
  </main>
</div>

<style>
  .shell {
    min-height: 100vh;
  }

  header {
    align-items: center;
    background: rgba(255, 255, 255, 0.96);
    border-bottom: 1px solid var(--border);
    display: grid;
    gap: var(--space-4);
    grid-template-columns: auto 1fr auto;
    min-height: 64px;
    padding: 0 var(--space-6);
    position: sticky;
    top: 0;
    z-index: 2;
  }

  .brand img {
    display: block;
    height: 32px;
    width: 159px;
  }

  nav {
    display: flex;
    gap: var(--space-4);
  }

  nav a {
    color: var(--text-muted);
    font-weight: 700;
    text-decoration: none;
  }

  nav a:hover {
    color: var(--text);
  }

  .user {
    align-items: center;
    display: flex;
    gap: var(--space-3);
  }

  .user span {
    color: var(--text-muted);
    font-size: 0.92rem;
  }

  .user button {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    cursor: pointer;
    min-height: 34px;
    padding: 0 var(--space-3);
  }

  main {
    margin: 0 auto;
    max-width: 1800px;
    padding: var(--space-6);
  }

  @media (max-width: 760px) {
    header {
      grid-template-columns: 1fr;
      padding: var(--space-3) var(--space-4);
    }

    main {
      padding: var(--space-4);
    }
  }
</style>
