import { describe, expect, it, vi } from 'vitest';
import { streamConsultation } from './consultations';

describe('streamConsultation', () => {
  it('parses normalized SSE events', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"delta","text":"A"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","elapsedMs":3}\n\n'));
        controller.close();
      }
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })));
    const events: unknown[] = [];
    await streamConsultation('question', (event) => events.push(event));
    expect(events).toEqual([
      { type: 'delta', text: 'A' },
      { type: 'done', elapsedMs: 3 }
    ]);
  });
});
