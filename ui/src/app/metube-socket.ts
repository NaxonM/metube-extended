import { ApplicationRef, Injectable } from '@angular/core';
import { Socket } from 'ngx-socket-io';

@Injectable()
export class MeTubeSocket extends Socket {
  constructor(appRef: ApplicationRef) {
    const path =
      document.location.pathname.replace(/share-target/, '') + 'socket.io';
    super({ url: '', options: { path, withCredentials: true } }, appRef);
  }
}
