import { BrowserModule } from '@angular/platform-browser';
import { NgModule, isDevMode } from '@angular/core';
import { HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { CookieService } from 'ngx-cookie-service';
import { ServiceWorkerModule } from '@angular/service-worker';

import { AppComponent } from './app.component';
import { MeTubeSocket } from './metube-socket';
import { AppRoutingModule } from './app-routing.module';
import { ApiPrefixInterceptor } from './api-prefix.interceptor';

@NgModule({
  declarations: [AppComponent],
  imports: [
    BrowserModule,
    AppRoutingModule,
    ServiceWorkerModule.register('custom-service-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000'
    })
  ],
  providers: [
    CookieService,
    MeTubeSocket,
    provideHttpClient(withInterceptorsFromDi()),
    { provide: HTTP_INTERCEPTORS, useClass: ApiPrefixInterceptor, multi: true }
  ],
  bootstrap: [AppComponent]
})
export class AppModule {}
