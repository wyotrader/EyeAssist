<script lang="ts">
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import Spinner from '$lib/components/common/Spinner.svelte';

  export let text = '';
  export let streaming = false;
  export let error = '';

  $: html = DOMPurify.sanitize(marked.parse(text || '') as string);
</script>

<section class="panel response" aria-live="polite" aria-busy={streaming}>
  <div class="heading">
    <div>
      <div class="eyebrow">EyeAssist Consultation</div>
      <h2>Clinical assessment</h2>
    </div>
    {#if streaming}
      <Spinner />
    {/if}
  </div>

  {#if error}
    <p class="error">{error}</p>
  {:else if text}
    <div class="markdown">{@html html}</div>
  {:else}
    <div class="empty">
      <h3>No consultation requested</h3>
      <p>Submit a text-only ophthalmic question to generate a structured consultation with retrieved evidence.</p>
    </div>
  {/if}
</section>

<style>
  .response {
    min-height: 520px;
    padding: var(--space-6);
  }

  .heading {
    align-items: center;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    margin-bottom: var(--space-5);
    padding-bottom: var(--space-4);
  }

  h2 {
    font-size: 1.45rem;
    margin: var(--space-2) 0 0;
  }

  .markdown {
    animation: fade-in 160ms ease;
    color: var(--text);
    font-size: 1.02rem;
    line-height: 1.65;
    max-width: 92ch;
  }

  .markdown :global(h1),
  .markdown :global(h2),
  .markdown :global(h3) {
    font-size: 1.05rem;
    margin: var(--space-5) 0 var(--space-2);
  }

  .markdown :global(p),
  .markdown :global(ul),
  .markdown :global(ol) {
    margin: 0 0 var(--space-4);
  }

  .empty {
    align-items: flex-start;
    background: var(--surface-muted);
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 340px;
    padding: var(--space-6);
  }

  .empty h3 {
    margin: 0 0 var(--space-2);
  }

  .empty p,
  .error {
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0;
  }

  .error {
    color: var(--danger);
    font-weight: 700;
  }
</style>
