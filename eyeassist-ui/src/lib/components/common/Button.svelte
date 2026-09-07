<script lang="ts">
  export let type: 'button' | 'submit' = 'button';
  export let variant: 'primary' | 'secondary' | 'danger' = 'primary';
  export let disabled = false;
</script>

<button class={variant} {type} {disabled} on:click>
  <slot />
</button>

<style>
  button {
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-weight: 700;
    min-height: 40px;
    padding: 0 var(--space-4);
    transition: background 120ms ease, border-color 120ms ease, opacity 120ms ease;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .primary {
    background: var(--accent);
    color: white;
  }

  .primary:hover:not(:disabled) {
    background: var(--accent-strong);
  }

  .secondary {
    background: var(--surface);
    border-color: var(--border);
    color: var(--text);
  }

  .danger {
    background: #fff5f3;
    border-color: #f3c7c0;
    color: var(--danger);
  }
</style>
