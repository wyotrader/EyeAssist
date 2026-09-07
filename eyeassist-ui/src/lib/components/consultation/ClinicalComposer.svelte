<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import Button from '$lib/components/common/Button.svelte';

  export let disabled = false;
  export let streaming = false;
  export let value = '';

  const dispatch = createEventDispatcher<{ submit: void; cancel: void }>();
</script>

<form class="panel composer" on:submit|preventDefault={() => dispatch('submit')}>
  <label for="question">Clinical question</label>
  <textarea
    id="question"
    bind:value
    disabled={disabled}
    rows="5"
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
    padding: var(--space-5);
  }

  label {
    display: block;
    font-size: 1.05rem;
    font-weight: 800;
    margin-bottom: var(--space-3);
  }

  textarea {
    background: var(--surface-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    color: var(--text);
    line-height: 1.5;
    min-height: 142px;
    padding: var(--space-4);
    resize: vertical;
    width: 100%;
  }

  .actions {
    align-items: center;
    display: flex;
    gap: var(--space-3);
    justify-content: space-between;
    margin-top: var(--space-4);
  }
</style>
