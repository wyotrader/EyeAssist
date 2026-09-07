import { api } from './client';
import type { HealthItem } from '$lib/types';

export function getHealth() {
  return api<{ services: HealthItem[] }>('/api/eyeassist/health');
}
