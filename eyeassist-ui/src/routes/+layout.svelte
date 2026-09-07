<script lang="ts">
  import '../app.css';
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import AppShell from '$lib/components/AppShell.svelte';
  import { getSession } from '$lib/api/auth';
  import { session } from '$lib/session';

  let ready = false;

  if (browser) {
    getSession()
      .then((user) => session.set(user))
      .catch(() => session.set(null))
      .finally(() => (ready = true));
  }

  $: if (browser && ready && !$session && location.pathname !== '/login') {
    goto('/login');
  }
</script>

{#if ready || !browser}
  <AppShell>
    <slot />
  </AppShell>
{/if}
