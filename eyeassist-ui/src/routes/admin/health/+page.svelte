<script lang="ts">
  import { onMount } from 'svelte';
  import StatusBadge from '$lib/components/common/StatusBadge.svelte';
  import { getHealth } from '$lib/api/admin';
  import type { HealthItem } from '$lib/types';

  let services: HealthItem[] = [];
  let error = '';
  let loading = true;

  onMount(async () => {
    try {
      services = (await getHealth()).services;
    } catch {
      error = 'System health is available to administrators only.';
    } finally {
      loading = false;
    }
  });
</script>

<section class="health">
  <div class="title">
    <div class="eyebrow">Administration</div>
    <h1>System health</h1>
  </div>

  <div class="panel table" aria-live="polite">
    {#if loading}
      <p class="muted">Checking services...</p>
    {:else if error}
      <p class="error" role="alert">{error}</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>Service</th>
            <th>Status</th>
            <th>Latency</th>
          </tr>
        </thead>
        <tbody>
          {#each services as item}
            <tr>
              <td>{item.name}</td>
              <td>
                <StatusBadge tone={item.available ? 'ok' : 'danger'}>
                  {item.status}
                </StatusBadge>
              </td>
              <td>{item.latencyMs === null ? 'Unavailable' : `${item.latencyMs} ms`}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</section>

<style>
  .health {
    display: grid;
    gap: var(--space-5);
  }

  h1 {
    font-size: clamp(1.7rem, 2vw, 2.4rem);
    margin: var(--space-2) 0 0;
  }

  .table {
    overflow: auto;
    padding: var(--space-5);
  }

  table {
    border-collapse: collapse;
    min-width: 640px;
    width: 100%;
  }

  th,
  td {
    border-bottom: 1px solid var(--border);
    padding: var(--space-4);
    text-align: left;
  }

  th {
    color: var(--text-muted);
    font-size: 0.82rem;
    text-transform: uppercase;
  }

  .error {
    color: var(--danger);
    font-weight: 700;
  }
</style>
