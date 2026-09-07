<script lang="ts">
  import type { EvidenceItem } from '$lib/types';

  export let items: EvidenceItem[] = [];
</script>

<aside class="panel evidence" aria-labelledby="evidence-title">
  <div class="eyebrow">Evidence</div>
  <h2 id="evidence-title">Retrieved references</h2>
  {#if items.length === 0}
    <p class="empty">Evidence will appear after retrieval completes.</p>
  {:else}
    <ol>
      {#each items as item}
        <li>
          <strong>{item.title}</strong>
          <span>{item.collection}{item.page ? `, p. ${item.page}` : ''}</span>
          {#if item.distance !== null}
            <small>distance {item.distance.toFixed(2)}</small>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</aside>

<style>
  .evidence {
    align-self: start;
    padding: var(--space-5);
  }

  h2 {
    font-size: 1rem;
    margin: var(--space-2) 0 var(--space-4);
  }

  .empty {
    color: var(--text-muted);
    line-height: 1.45;
    margin: 0;
  }

  ol {
    display: grid;
    gap: var(--space-3);
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    border-left: 3px solid var(--accent);
    padding-left: var(--space-3);
  }

  strong,
  span,
  small {
    display: block;
  }

  strong {
    font-size: 0.95rem;
    line-height: 1.35;
  }

  span,
  small {
    color: var(--text-muted);
    font-size: 0.84rem;
    margin-top: var(--space-1);
  }
</style>
