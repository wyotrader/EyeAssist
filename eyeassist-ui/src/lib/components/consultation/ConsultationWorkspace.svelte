<script lang="ts">
  import Button from '$lib/components/common/Button.svelte';
  import ClinicalComposer from './ClinicalComposer.svelte';
  import EvidencePanel from './EvidencePanel.svelte';
  import ResponsePanel from './ResponsePanel.svelte';
  import { streamConsultation } from '$lib/api/consultations';
  import type { EvidenceItem } from '$lib/types';

  let question = '';
  let lastQuestion = '';
  let response = '';
  let status = '';
  let error = '';
  let streaming = false;
  let evidence: EvidenceItem[] = [];
  let controller: AbortController | null = null;

  async function submit() {
    if (!question.trim() || streaming) return;
    lastQuestion = question;
    response = '';
    error = '';
    evidence = [];
    streaming = true;
    status = 'Preparing consultation';
    controller = new AbortController();

    try {
      await streamConsultation(
        question.trim(),
        (event) => {
          if (event.type === 'status') status = event.label;
          if (event.type === 'evidence') evidence = event.items;
          if (event.type === 'delta') response += event.text;
          if (event.type === 'error') error = event.message;
          if (event.type === 'done') status = `Completed in ${event.elapsedMs} ms`;
        },
        controller.signal
      );
    } catch (err) {
      if (!controller.signal.aborted) error = err instanceof Error ? err.message : 'Consultation failed.';
    } finally {
      streaming = false;
      controller = null;
    }
  }

  function cancel() {
    controller?.abort();
    status = 'Cancelled';
    streaming = false;
  }

  function retry() {
    question = lastQuestion;
    void submit();
  }
</script>

<div class="workspace">
  <section class="title">
    <div>
      <div class="eyebrow">Clinical consultation</div>
      <h1>Ophthalmic question workspace</h1>
    </div>
    {#if status}
      <p>{status}</p>
    {/if}
  </section>

  <ClinicalComposer bind:value={question} disabled={streaming} {streaming} on:submit={submit} on:cancel={cancel}>
    <span slot="status" class="muted">{streaming ? status : 'Text-only first slice'}</span>
  </ClinicalComposer>

  <div class="content">
    <div>
      <ResponsePanel text={response} {streaming} {error} />
      {#if lastQuestion && !streaming}
        <div class="retry">
          <Button variant="secondary" on:click={retry}>Retry consultation</Button>
        </div>
      {/if}
    </div>
    <EvidencePanel items={evidence} />
  </div>
</div>

<style>
  .workspace {
    display: grid;
    gap: var(--space-5);
  }

  .title {
    align-items: end;
    display: flex;
    gap: var(--space-4);
    justify-content: space-between;
  }

  h1 {
    font-size: clamp(1.7rem, 2vw, 2.4rem);
    line-height: 1.1;
    margin: var(--space-2) 0 0;
  }

  .title p {
    color: var(--text-muted);
    margin: 0;
  }

  .content {
    display: grid;
    gap: var(--space-5);
    grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
  }

  .retry {
    margin-top: var(--space-4);
  }

  @media (max-width: 1060px) {
    .content {
      grid-template-columns: 1fr;
    }

    .title {
      align-items: start;
      flex-direction: column;
    }
  }
</style>
