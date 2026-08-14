"""
WebSocket endpoint for the live audio -> transcript -> translation pipeline.

This is a thin transport layer: it accepts the connection, parses
client control/audio messages, and will delegate to the ASR/translation/
LLM providers (via their abstract interfaces) once those are
implemented. The actual pipeline orchestration (buffering, provider
selection, silence-triggered finalization, async refinement dispatch)
is intentionally left as the next build step -- see
DEVELOPMENT_PLAN.md Phase 2.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.schemas import ErrorMessage, WSServerEventType

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/audio")
async def audio_stream(websocket: WebSocket) -> None:
    """
    Protocol (see app/models/schemas.py for exact payloads):
      Client -> Server:
        - JSON {"type": "start", ...SessionStartRequest}
        - binary frames: raw PCM16/Opus audio chunks
        - JSON {"type": "silence", "duration_ms": N} (from client-side Silero VAD)
        - JSON {"type": "stop"}
      Server -> Client:
        - JSON {"type": "transcript_partial" | "transcript_final", ...}
        - JSON {"type": "translation_partial" | "translation_final", ...}
        - JSON {"type": "refinement", ...}   (sent later, async)
        - JSON {"type": "status" | "error" | "latency", ...}
    """
    await websocket.accept()
    session_id = id(websocket)
    logger.info("ws_connected", session_id=session_id)

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                # TODO: parse control messages (start/silence/stop) into
                # app.models.schemas types and drive the pipeline.
                logger.debug("ws_text_message", session_id=session_id, raw=message["text"])
                continue

            if "bytes" in message and message["bytes"] is not None:
                # TODO: forward to the active ASRProvider.send_audio(chunk)
                logger.debug(
                    "ws_audio_chunk",
                    session_id=session_id,
                    bytes=len(message["bytes"]),
                )
                continue

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    except Exception as exc:  # surface as a structured error to the client
        logger.exception("ws_error", session_id=session_id)
        try:
            await websocket.send_json(
                {
                    "type": WSServerEventType.ERROR.value,
                    **ErrorMessage(code="internal_error", message=str(exc)).model_dump(),
                }
            )
        except Exception:  # connection may already be closed
            logger.debug("ws_send_error_ignored", session_id=session_id)
