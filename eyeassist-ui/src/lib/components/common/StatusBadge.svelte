<script lang="ts">
  export let tone: 'ok' | 'warn' | 'danger' | 'unknown' = 'unknown';
</script>

<span class={tone}>
  <slot />
</span>

<style>
  span {
    border-radius: 999px;
    display: inline-flex;
    font-size: 0.82rem;
    font-weight: 700;
    gap: var(--space-2);
    line-height: 1;
    padding: 6px 10px;
  }

  span::before {
    border-radius: 999px;
    content: '';
    height: 8px;
    margin-top: 1px;
    width: 8px;
  }

  .ok {
    background: #eaf7ef;
    color: var(--ok);
  }

  .ok::before {
    background: var(--ok);
  }

  .warn {
    background: #fff7df;
    color: var(--warn);
  }

  .warn::before {
    background: var(--warn);
  }

  .danger {
    background: #fff1ef;
    color: var(--danger);
  }

  .danger::before {
    background: var(--danger);
  }

  .unknown {
    background: var(--surface-strong);
    color: var(--unknown);
  }

  .unknown::before {
    background: var(--unknown);
  }
</style>
