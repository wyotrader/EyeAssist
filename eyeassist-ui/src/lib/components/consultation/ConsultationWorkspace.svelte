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
  let stage: 'idle' | 'retrieval' | 'synthesis' | 'generation' | 'done' | 'cancelled' | 'error' = 'idle';
  let error = '';
  let streaming = false;
  let canRetry = false;
  let evidence: EvidenceItem[] = [];
  let controller: AbortController | null = null;

  $: visibleStatus = streaming && response ? 'Generating response' : status;
  $: statusTone = stage === 'error' ? 'danger' : stage === 'cancelled' ? 'warn' : stage === 'done' ? 'ok' : 'active';

  async function submit() {
    if (!question.trim() || streaming) return;
    lastQuestion = question;
    response = '';
    error = '';
    evidence = [];
    canRetry = false;
    streaming = true;
    stage = 'retrieval';
    status = 'Retrieving evidence';
    controller = new AbortController();

    try {
      await streamConsultation(
        question.trim(),
        (event) => {
          if (event.type === 'status') {
            stage = event.stage === 'synthesis' ? 'synthesis' : 'retrieval';
            status = stage === 'synthesis' ? 'Synthesizing consultation' : 'Retrieving evidence';
          }
          if (event.type === 'evidence') evidence = event.items;
          if (event.type === 'delta') {
            stage = 'generation';
            response += event.text;
          }
          if (event.type === 'error') {
            stage = 'error';
            error = event.message;
            canRetry = true;
          }
          if (event.type === 'done') {
            stage = 'done';
            status = `Completed in ${event.elapsedMs} ms`;
          }
        },
        controller.signal
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        stage = 'error';
        error = err instanceof Error ? err.message : 'Consultation failed.';
        status = 'Consultation failed';
        canRetry = true;
      }
    } finally {
      streaming = false;
      controller = null;
    }
  }

  function cancel() {
    controller?.abort();
    stage = 'cancelled';
    status = 'Cancelled';
    canRetry = true;
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
    {#if visibleStatus}
      <p class:active={statusTone === 'active'} class:ok={statusTone === 'ok'} class:warn={statusTone === 'warn'} class:danger={statusTone === 'danger'}>{visibleStatus}</p>
    {/if}
  </section>

  <ClinicalComposer bind:value={question} disabled={streaming} {streaming} on:submit={submit} on:cancel={cancel} />

  <div class="content">
    <div>
      <ResponsePanel text={response} {streaming} {error} status={streaming && response ? 'Generating response' : ''} />
      {#if canRetry && lastQuestion && !streaming}
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
    gap: var(--space-4);
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
    align-items: center;
    color: var(--text-muted);
    display: inline-flex;
    font-size: 0.9rem;
    font-weight: 700;
    gap: var(--space-2);
    margin: 0;
  }

  .title p::before,
  .title p::before {
    border-radius: 999px;
    content: '';
    height: 8px;
    width: 8px;
  }

  .title p.active::before {
    animation: pulse 1.4s ease-in-out infinite;
    background: var(--accent);
  }

  .title p.ok::before {
    background: var(--ok);
  }

  .title p.warn::before {
    background: var(--warn);
  }

  .title p.danger::before {
    background: var(--danger);
  }

  .content {
    display: grid;
    gap: var(--space-5);
    grid-template-columns: minmax(0, 1fr) minmax(300px, 380px);
    align-items: start;
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

  @keyframes pulse {
    0%,
    100% {
      opacity: 0.45;
    }
    50% {
      opacity: 1;
    }
  }
</style>
