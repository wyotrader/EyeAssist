<script lang="ts">
</script>

<span aria-label="Loading" role="status"></span>

<style>
  span {
    animation: spin 800ms linear infinite;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 999px;
    display: inline-block;
    height: 18px;
    width: 18px;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
