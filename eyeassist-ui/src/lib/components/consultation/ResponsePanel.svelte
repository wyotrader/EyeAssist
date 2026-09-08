<script lang="ts">
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import Spinner from '$lib/components/common/Spinner.svelte';

  export let text = '';
  export let streaming = false;
  export let error = '';
  export let status = '';

  $: html = DOMPurify.sanitize(marked.parse(text || '') as string);
</script>

<section class="panel response" aria-live="polite" aria-busy={streaming}>
  <div class="heading">
    <div>
      <div class="eyebrow">EyeAssist Consultation</div>
      <h2>Clinical assessment</h2>
    </div>
    {#if streaming && !text}
      <div class="loading">
        <Spinner />
        <span>Preparing response</span>
      </div>
    {:else if streaming && status}
      <span class="inline-status">{status}</span>
    {/if}
  </div>

  {#if error}
    <p class="error">{error}</p>
  {:else if streaming && !text}
    <div class="empty loading-state">
      <h3>Preparing clinical assessment</h3>
      <p>Evidence has been requested and synthesis will begin shortly.</p>
    </div>
  {:else if text}
    <div class="markdown">{@html html}</div>
  {:else}
    <div class="empty">
      <h3>Ready for a clinical question</h3>
      <p>Submit an ophthalmic question to generate a structured consultation with retrieved evidence.</p>
    </div>
  {/if}
</section>

<style>
  .response {
    min-height: 560px;
    padding: var(--space-5) var(--space-6);
  }

  .heading {
    align-items: center;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    margin-bottom: var(--space-4);
    padding-bottom: var(--space-3);
  }

  h2 {
    font-size: 1.32rem;
    margin: var(--space-2) 0 0;
  }

  .loading,
  .inline-status {
    align-items: center;
    color: var(--text-muted);
    display: inline-flex;
    font-size: 0.86rem;
    font-weight: 700;
    gap: var(--space-2);
    white-space: nowrap;
  }

  .inline-status::before {
    background: var(--accent);
    border-radius: 999px;
    content: '';
    height: 7px;
    width: 7px;
  }

  .markdown {
    animation: fade-in 160ms ease;
    color: var(--text);
    font-size: 1rem;
    line-height: 1.68;
    max-width: 88ch;
  }

  .markdown :global(h1),
  .markdown :global(h2),
  .markdown :global(h3) {
    color: #1d3346;
    font-size: 1.02rem;
    line-height: 1.35;
    margin: var(--space-5) 0 var(--space-2);
  }

  .markdown :global(p),
  .markdown :global(ul),
  .markdown :global(ol) {
    margin: 0 0 var(--space-4);
  }

  .markdown :global(ul),
  .markdown :global(ol) {
    padding-left: var(--space-5);
  }

  .markdown :global(li) {
    margin-bottom: var(--space-2);
  }

  .markdown :global(strong) {
    color: #10283a;
  }

  .markdown :global(a) {
    color: var(--accent-strong);
    font-weight: 700;
    text-decoration-thickness: 2px;
    text-underline-offset: 3px;
  }

  .empty {
    align-items: flex-start;
    background: var(--surface-muted);
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 360px;
    padding: var(--space-6);
  }

  .empty h3 {
    color: var(--text);
    font-size: 1.12rem;
    margin: 0 0 var(--space-2);
  }

  .empty p,
  .error {
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0;
  }

  .loading-state {
    border-style: solid;
  }

  .error {
    color: var(--danger);
    font-weight: 700;
  }
</style>
