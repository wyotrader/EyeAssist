import type { StreamEvent } from '$lib/types';

export async function streamConsultation(
  message: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
) {
  const res = await fetch('/api/eyeassist/consultations/stream', {
    method: 'POST',
    credentials: 'include',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message }),
    signal
  });

  if (!res.ok || !res.body) {
    throw new Error(res.status === 403 ? 'Sign in required.' : 'Consultation request failed.');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';

    for (const part of parts) {
      const line = part.split('\n').find((row) => row.startsWith('data:'));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(5).trim()) as StreamEvent);
    }
  }
}
