import { writable } from 'svelte/store';
import type { UserSession } from '$lib/types';

export const session = writable<UserSession | null>(null);
