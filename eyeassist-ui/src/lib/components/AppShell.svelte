<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { session } from '$lib/session';
  import { getHealth } from '$lib/api/admin';
  import { logout } from '$lib/api/auth';

  let healthLabel = 'System ready';
  let healthTone: 'ok' | 'warn' | 'danger' | 'unknown' = 'unknown';

  onMount(async () => {
    if ($session?.role !== 'admin') {
      healthTone = 'ok';
      return;
    }

    try {
      const result = await getHealth();
      const unavailable = result.services.filter((service) => !service.available);
      healthTone = unavailable.length === 0 ? 'ok' : 'warn';
      healthLabel = unavailable.length === 0 ? 'All systems' : `${unavailable.length} degraded`;
    } catch {
      healthTone = 'unknown';
      healthLabel = 'Health unavailable';
    }
  });

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
    {#if $session}
      <div class="system" class:ok={healthTone === 'ok'} class:warn={healthTone === 'warn'} class:danger={healthTone === 'danger'} class:unknown={healthTone === 'unknown'}>
        {#if $session.role === 'admin'}
          <a href="/admin/health" aria-label="System health">{healthLabel}</a>
        {:else}
          <span>{healthLabel}</span>
        {/if}
      </div>
      <div class="identity">
        <div>
          <strong>{$session.name}</strong>
          <span>{$session.role === 'admin' ? 'Administrator' : 'Clinician'}</span>
        </div>
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
    min-height: 58px;
    padding: 0 var(--space-5);
    position: sticky;
    top: 0;
    z-index: 2;
  }

  .brand img {
    display: block;
    height: 32px;
    width: 159px;
  }

  .system {
    align-items: center;
    color: var(--text-muted);
    display: inline-flex;
    font-size: 0.82rem;
    font-weight: 700;
    gap: var(--space-2);
    justify-self: start;
  }

  .system::before {
    border-radius: 999px;
    content: '';
    height: 8px;
    width: 8px;
  }

  .system a {
    text-decoration: none;
  }

  .system a:hover {
    color: var(--text);
  }

  .system.ok::before {
    background: var(--ok);
  }

  .system.warn::before {
    background: var(--warn);
  }

  .system.danger::before {
    background: var(--danger);
  }

  .system.unknown::before {
    background: var(--unknown);
  }

  .identity {
    align-items: center;
    display: flex;
    gap: var(--space-3);
  }

  .identity div {
    display: grid;
    gap: 2px;
    justify-items: end;
  }

  .identity strong {
    color: var(--text);
    font-size: 0.9rem;
    line-height: 1.1;
  }

  .identity span {
    color: var(--text-muted);
    font-size: 0.76rem;
    line-height: 1.1;
  }

  .identity button {
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
    padding: var(--space-5);
  }

  @media (max-width: 760px) {
    header {
      gap: var(--space-3);
      grid-template-columns: 1fr;
      padding: var(--space-3) var(--space-4);
    }

    .system {
      justify-self: start;
    }

    .identity {
      justify-content: space-between;
      width: 100%;
    }

    .identity div {
      justify-items: start;
    }

    main {
      padding: var(--space-4);
    }
  }
</style>
