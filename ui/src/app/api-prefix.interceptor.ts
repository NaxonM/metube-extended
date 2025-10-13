import { Injectable } from '@angular/core';
import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Observable } from 'rxjs';

import { buildApiUrl, getApiBase } from './api-base.util';

@Injectable()
export class ApiPrefixInterceptor implements HttpInterceptor {
  private readonly apiBase = getApiBase();

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    if (this.isAbsoluteUrl(req.url)) {
      return next.handle(req);
    }

    const url = buildApiUrl(req.url);
    return next.handle(req.clone({ url }));
  }

  private isAbsoluteUrl(url: string): boolean {
    return /^([a-z][a-z0-9+.-]*:)?\/\//i.test(url);
  }
}
