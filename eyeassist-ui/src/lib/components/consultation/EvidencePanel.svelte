<script lang="ts">
  import type { EvidenceItem } from '$lib/types';

  export let items: EvidenceItem[] = [];
</script>

<aside class="panel evidence" aria-labelledby="evidence-title">
  <div class="heading">
    <div>
      <div class="eyebrow">Evidence</div>
      <h2 id="evidence-title">Retrieved references</h2>
    </div>
    {#if items.length}
      <span>{items.length}</span>
    {/if}
  </div>
  {#if items.length === 0}
    <p class="empty">Retrieved citations will appear here after evidence search completes.</p>
  {:else}
    <ol>
      {#each items as item}
        <li>
          <strong>{item.title}</strong>
          <div>
            {#if item.page}
              <span>p. {item.page}</span>
            {/if}
            <span>{item.collection || 'source'}</span>
          </div>
          {#if item.distance !== null}
            <small>match distance {item.distance.toFixed(2)}</small>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</aside>

<style>
  .evidence {
    align-self: stretch;
    max-height: calc(100vh - 204px);
    overflow: auto;
    padding: var(--space-4);
    position: sticky;
    top: 82px;
  }

  .heading {
    align-items: start;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    margin-bottom: var(--space-4);
    padding-bottom: var(--space-3);
  }

  h2 {
    font-size: 1rem;
    margin: var(--space-2) 0 0;
  }

  .heading > span {
    background: var(--surface-strong);
    border-radius: 999px;
    color: var(--text-muted);
    font-size: 0.78rem;
    font-weight: 800;
    min-width: 26px;
    padding: 5px 8px;
    text-align: center;
  }

  .empty {
    color: var(--text-muted);
    line-height: 1.45;
    margin: 0;
  }

  ol {
    display: grid;
    gap: var(--space-4);
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    border-bottom: 1px solid var(--border);
    padding-bottom: var(--space-4);
  }

  li:last-child {
    border-bottom: 0;
    padding-bottom: 0;
  }

  strong {
    display: block;
    font-size: 0.95rem;
    line-height: 1.35;
  }

  div {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  span {
    background: var(--surface-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1;
    padding: 5px 7px;
  }

  small {
    color: var(--text-muted);
    display: block;
    font-size: 0.78rem;
    margin-top: var(--space-2);
  }

  @media (max-width: 1060px) {
    .evidence {
      max-height: none;
      position: static;
    }
  }
</style>
