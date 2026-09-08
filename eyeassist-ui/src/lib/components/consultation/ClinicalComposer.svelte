<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import Button from '$lib/components/common/Button.svelte';

  export let disabled = false;
  export let streaming = false;
  export let value = '';

  const dispatch = createEventDispatcher<{ submit: void; cancel: void }>();
  let textarea: HTMLTextAreaElement;

  $: if (textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }
</script>

<form class="panel composer" on:submit|preventDefault={() => dispatch('submit')}>
  <label for="question">Clinical question</label>
  <textarea
    bind:this={textarea}
    id="question"
    bind:value
    disabled={disabled}
    rows="3"
    placeholder="Ask an ophthalmic consultation question..."
  ></textarea>
  <div class="actions">
    <slot name="status" />
    {#if streaming}
      <Button variant="danger" on:click={() => dispatch('cancel')}>Cancel</Button>
    {:else}
      <Button type="submit" disabled={disabled || !value.trim()}>Request consultation</Button>
    {/if}
  </div>
</form>

<style>
  .composer {
    padding: var(--space-4) var(--space-5);
  }

  label {
    display: block;
    font-size: 1.08rem;
    font-weight: 800;
    margin-bottom: var(--space-2);
  }

  textarea {
    background: var(--surface-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    color: var(--text);
    line-height: 1.5;
    min-height: 84px;
    overflow: hidden;
    padding: var(--space-3) var(--space-4);
    resize: none;
    width: 100%;
  }

  textarea:focus {
    background: var(--surface);
    border-color: var(--focus);
  }

  .actions {
    align-items: center;
    display: flex;
    gap: var(--space-3);
    justify-content: space-between;
    margin-top: var(--space-3);
  }

  @media (max-width: 700px) {
    .actions {
      align-items: stretch;
      flex-direction: column;
    }
  }
</style>
