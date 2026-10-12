import { getToken } from './api';

/** Atualiza as telas por eventos em tempo real. Fallback: polling e foco da aba.
 * Os eventos NÃO contêm dados dos moradores; cada tela consulta sua API autorizada.
 */
export function watchChanges(onChange: () => void): () => void {
  const controller = new AbortController();
  let lastEvent = 0;
  const refresh = () => {
    const now = Date.now();
    if (now - lastEvent > 600) {
      lastEvent = now;
      onChange();
    }
  };
  const interval = window.setInterval(refresh, 15000);
  const onFocus = () => refresh();
  const onVisibility = () => { if (document.visibilityState === 'visible') refresh(); };
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', onVisibility);

  const listen = async () => {
    while (!controller.signal.aborted) {
      try {
        const token = getToken();
        if (!token) break;
        const response = await fetch('/api/events', {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          cache: 'no-store', signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          if (response.status === 401) break;
          throw new Error('Stream indisponível');
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let data = '';
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          data += decoder.decode(value, { stream: true });
          const frames = data.split('\n\n');
          data = frames.pop() || '';
          if (frames.some(frame => frame.split('\n').includes('event: update'))) refresh();
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      if (!controller.signal.aborted) {
        await new Promise(resolve => window.setTimeout(resolve, 2500));
      }
    }
  };
  void listen();
  return () => {
    controller.abort();
    window.clearInterval(interval);
    window.removeEventListener('focus', onFocus);
    document.removeEventListener('visibilitychange', onVisibility);
  };
}
