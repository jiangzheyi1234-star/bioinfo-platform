"use client";

type CacheEntry<T> = {
  value?: T;
  expiresAt: number;
  inFlight?: Promise<T>;
};

const cache = new Map<string, CacheEntry<unknown>>();

export async function cachedAsync<T>(
  key: string,
  ttlMs: number,
  loader: () => Promise<T>,
  options: { forceRefresh?: boolean } = {}
): Promise<T> {
  const now = Date.now();
  const current = cache.get(key) as CacheEntry<T> | undefined;

  if (!options.forceRefresh && current?.value !== undefined && current.expiresAt > now) {
    return current.value;
  }
  if (!options.forceRefresh && current?.inFlight) {
    return current.inFlight;
  }

  const inFlight = loader().then((value) => {
    cache.set(key, { value, expiresAt: Date.now() + ttlMs });
    return value;
  }).catch((error) => {
    const latest = cache.get(key);
    if (latest?.inFlight === inFlight) {
      cache.delete(key);
    }
    throw error;
  });

  cache.set(key, { value: current?.value, expiresAt: current?.expiresAt || 0, inFlight });
  return inFlight;
}

export function peekAsyncCache<T>(key: string): T | undefined {
  const current = cache.get(key) as CacheEntry<T> | undefined;
  if (current?.value !== undefined && current.expiresAt > Date.now()) {
    return current.value;
  }
  return undefined;
}

export function invalidateAsyncCache(key: string) {
  cache.delete(key);
}

export function invalidateAsyncCachePrefix(prefix: string) {
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) {
      cache.delete(key);
    }
  }
}
