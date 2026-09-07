import { api } from './client';
import type { UserSession } from '$lib/types';

export function login(email: string, password: string) {
  return api<UserSession>('/api/eyeassist/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password })
  });
}

export function getSession() {
  return api<UserSession>('/api/eyeassist/session');
}

export async function logout() {
  await api<{ ok: true }>('/api/eyeassist/session', { method: 'DELETE' });
}
