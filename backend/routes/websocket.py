# -*- coding: utf-8 -*-
"""WebSocket 路由"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.ws_service import ws_manager, log_manager
from backend.services.logging_service import log_info

router = APIRouter(tags=["websocket"])

@router.websocket("/ws/directory-watch")
async def websocket_directory_watch(websocket: WebSocket):
    """目录变化监控 WebSocket"""
    await ws_manager.connect(websocket, "directory")
    try:
        while True:
            # 保持连接，等待客户端消息（如心跳）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "directory")
    except Exception as e:
        log_info(f"[WebSocket] directory-watch 连接异常: {e}")
        ws_manager.disconnect(websocket, "directory")


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """实时日志 WebSocket"""
    await ws_manager.connect(websocket, "logs")
    
    # 发送最近的日志
    recent_logs = log_manager.get_recent_logs(50)
    for log in recent_logs:
        await websocket.send_json(log)
    
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "logs")
    except Exception as e:
        log_info(f"[WebSocket] logs 连接异常: {e}")
        ws_manager.disconnect(websocket, "logs")
