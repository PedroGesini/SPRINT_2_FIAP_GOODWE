"""Pub/sub local para clientes autenticados de um mesmo condomínio.

Quando a aplicação usar múltiplos workers/hosts, substituir por Redis pub/sub.
"""
import asyncio
from collections import defaultdict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from app.core.permissions import get_current_user
from app.models import User

router = APIRouter(tags=['Sincronização'])
_clients: dict[int, set[asyncio.Queue]] = defaultdict(set)

async def publish(condominium_id: int):
    for queue in tuple(_clients.get(condominium_id, ())):
        if queue.full():
            try: queue.get_nowait()
            except asyncio.QueueEmpty: pass
        try: queue.put_nowait(True)
        except asyncio.QueueFull: pass

@router.get('/events')
async def events(request: Request, user: User = Depends(get_current_user)):
    condo = user.condominium_id
    queue: asyncio.Queue = asyncio.Queue(maxsize=4)
    async def generate():
        _clients[condo].add(queue)
        try:
            yield 'event: connected\ndata: {}\n\n'
            while not await request.is_disconnected():
                try:
                    await asyncio.wait_for(queue.get(), timeout=20)
                    # Evento intencionalmente sem dados; o cliente refaz consultas autorizadas.
                    yield 'event: update\ndata: {}\n\n'
                except asyncio.TimeoutError:
                    yield ': keepalive\n\n'
        finally:
            _clients[condo].discard(queue)
            if not _clients[condo]: _clients.pop(condo, None)
    return StreamingResponse(generate(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})
