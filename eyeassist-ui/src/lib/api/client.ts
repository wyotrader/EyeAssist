export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      ...init.headers
    }
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json()).detail ?? message;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, message);
  }

  return (await res.json()) as T;
}
