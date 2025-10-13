const cachedBase = resolveBaseInternal();

function resolveBaseInternal(): string {
  try {
    const manifest = document.querySelector('link[rel="manifest"]') as HTMLLinkElement | null;
    const href = manifest?.getAttribute('href') ?? 'manifest.webmanifest';
    const manifestUrl = new URL(href, window.location.href);
    const path = manifestUrl.pathname || '/';
    const base = path.endsWith('/') ? path : path.slice(0, path.lastIndexOf('/') + 1);
    return ensureTrailingSlash(base || '/');
  } catch {
    return '/';
  }
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}

export function getApiBase(): string {
  return cachedBase;
}

export function buildApiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path.substring(1) : path;
  return `${cachedBase}${normalized}`;
}
