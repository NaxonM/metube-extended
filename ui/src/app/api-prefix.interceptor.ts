import { Injectable } from '@angular/core';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable()
export class ApiPrefixInterceptor implements HttpInterceptor {
  private readonly apiBase: string;

  constructor() {
    this.apiBase = this.resolveApiBase();
  }

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    if (this.isAbsoluteUrl(req.url)) {
      return next.handle(req);
    }

    const base = this.ensureTrailingSlash(this.apiBase);
    const path = req.url.startsWith('/') ? req.url.substring(1) : req.url;
    const url = `${base}${path}`;
    return next.handle(req.clone({ url }));
  }

  private resolveApiBase(): string {
    try {
      const manifest = document.querySelector('link[rel="manifest"]') as HTMLLinkElement | null;
      const href = manifest?.getAttribute('href') ?? 'manifest.webmanifest';
      const manifestUrl = new URL(href, window.location.href);
      const path = manifestUrl.pathname;
      if (!path) {
        return '/';
      }

      if (path.endsWith('/')) {
        return path;
      }

      const index = path.lastIndexOf('/');
      if (index === -1) {
        return '/';
      }

      const prefix = path.slice(0, index + 1);
      return prefix || '/';
    } catch {
      return '/';
    }
  }

  private ensureTrailingSlash(value: string): string {
    return value.endsWith('/') ? value : `${value}/`;
  }

  private isAbsoluteUrl(url: string): boolean {
    return /^([a-z][a-z0-9+.-]*:)?\/\//i.test(url);
  }
}
