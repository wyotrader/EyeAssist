export type Role = 'admin' | 'clinician';

export type UserSession = {
  id: string;
  name: string;
  email: string;
  role: Role;
};

export type EvidenceItem = {
  title: string;
  page: number | null;
  collection: string;
  distance: number | null;
};

export type HealthItem = {
  name: 'gateway' | 'orchestrator' | 'rag' | 'vision' | 'ollama';
  available: boolean;
  status: string;
  latencyMs: number | null;
};

export type StreamEvent =
  | { type: 'session'; consultationId: string }
  | { type: 'status'; stage: string; label: string }
  | { type: 'evidence'; items: EvidenceItem[] }
  | { type: 'delta'; text: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; elapsedMs: number };
