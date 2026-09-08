import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import cards, dice, kp, rooms, suggestions
from app.ws import rooms as ws_rooms


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """3.4：启动服务端心跳踢除后台协程（清理 vite 代理抖动遗留的僵尸连接）。"""
    task = asyncio.create_task(ws_rooms.prune_stale_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {"status": "OK", "message": "Health check success"}

app.include_router(cards.router, prefix='/api')
app.include_router(dice.router, prefix='/api')
app.include_router(rooms.router, prefix='/api')
app.include_router(kp.router, prefix='/api')
# 阶段 4.1：协同建议（模式切换 / 手动触发）+ LLM 状态与连通性
app.include_router(suggestions.router, prefix='/api')
# WS 路由不带 /api 前缀：路径即 /ws/{room_id}
app.include_router(ws_rooms.router)