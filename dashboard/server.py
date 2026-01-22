"""
Dashboard Server
================

FastAPI server for the Polymarket trading dashboard.
Serves static files and provides WebSocket real-time updates.
"""

import asyncio
import json
from pathlib import Path
from typing import Set, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Get the dashboard directory
DASHBOARD_DIR = Path(__file__).parent
STATIC_DIR = DASHBOARD_DIR / "static"

app = FastAPI(title="Polymarket Trading Dashboard")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.bot_status = {
            "running": False,
            "dry_run": True,
            "last_update": None
        }
        self.portfolio = {
            "value": 10000.00,
            "pnl_today": 0.00,
            "pnl_percent": 0.00,
            "win_rate": 0.0,
            "total_trades": 0,
            "winning_trades": 0
        }
        self.positions = []
        self.trades = []
        self.markets = []
        self.btc_price = 0.0
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        # Send initial state
        await self.send_full_state(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
    
    async def send_full_state(self, websocket: WebSocket):
        """Send full dashboard state to a client."""
        # Get state from paper trading engine if running
        if paper_engine and paper_engine.running:
            state_data = paper_engine.get_state()
            self.portfolio = state_data["portfolio"]
            self.positions = state_data["positions"]
            self.trades = state_data["trades"]
            self.markets = state_data["markets"]
            self.btc_price = state_data["btc_price"]
        
        state = {
            "type": "full_state",
            "data": {
                "bot_status": self.bot_status,
                "portfolio": self.portfolio,
                "positions": self.positions,
                "trades": self.trades[-50:],
                "markets": self.markets,
                "btc_price": self.btc_price,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        await websocket.send_json(state)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Clean up disconnected clients
        self.active_connections -= disconnected


# Global connection manager and paper trading engine
manager = ConnectionManager()
paper_engine: Optional["PaperTradingEngine"] = None


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Handle client commands if needed
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# REST API endpoints
@app.get("/api/status")
async def get_status():
    """Get current bot status."""
    portfolio = manager.portfolio
    if paper_engine:
        portfolio = paper_engine._get_portfolio()
    
    return JSONResponse({
        "bot_status": manager.bot_status,
        "portfolio": portfolio,
        "connected_clients": len(manager.active_connections)
    })


@app.get("/api/markets")
async def get_markets():
    """Get active markets."""
    try:
        from src.data.market_discovery import discover_15min_btc_markets
        markets = await discover_15min_btc_markets()
        manager.markets = markets
        return JSONResponse({"markets": markets})
    except Exception as e:
        return JSONResponse({"markets": [], "error": str(e)})


@app.get("/api/trades")
async def get_trades():
    """Get trade history."""
    trades = manager.trades
    if paper_engine:
        trades = [t.to_dict() for t in paper_engine.trades]
    return JSONResponse({"trades": trades[-100:]})


@app.post("/api/bot/start")
async def start_bot():
    """Start the paper trading bot."""
    global paper_engine
    
    from dashboard.paper_trading import PaperTradingEngine
    
    if paper_engine and paper_engine.running:
        return JSONResponse({"success": False, "error": "Bot already running"})
    
    # Create and start paper trading engine
    paper_engine = PaperTradingEngine(broadcast_callback=manager.broadcast)
    await paper_engine.start()
    
    manager.bot_status["running"] = True
    manager.bot_status["last_update"] = datetime.now(timezone.utc).isoformat()
    
    await manager.broadcast({
        "type": "bot_status",
        "data": {"bot_status": manager.bot_status}
    })
    
    return JSONResponse({"success": True, "status": manager.bot_status})


@app.post("/api/bot/stop")
async def stop_bot():
    """Stop the paper trading bot."""
    global paper_engine
    
    if paper_engine:
        await paper_engine.stop()
    
    manager.bot_status["running"] = False
    manager.bot_status["last_update"] = datetime.now(timezone.utc).isoformat()
    
    await manager.broadcast({
        "type": "bot_status",
        "data": {"bot_status": manager.bot_status}
    })
    
    return JSONResponse({"success": True, "status": manager.bot_status})


@app.post("/api/bot/toggle-dry-run")
async def toggle_dry_run():
    """Toggle dry run mode."""
    manager.bot_status["dry_run"] = not manager.bot_status["dry_run"]
    manager.bot_status["last_update"] = datetime.now(timezone.utc).isoformat()
    await manager.broadcast({
        "type": "bot_status",
        "data": {"bot_status": manager.bot_status}
    })
    return JSONResponse({"success": True, "status": manager.bot_status})


# Serve static files
@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    """Start background tasks."""
    print("\n" + "="*50)
    print(">>> Polymarket Trading Dashboard <<<")
    print("="*50)
    print(f"[*] Dashboard: http://localhost:8080")
    print(f"[*] WebSocket: ws://localhost:8080/ws")
    print(f"[*] API Docs: http://localhost:8080/docs")
    print(f"[*] Paper Trading: Click 'Start Bot' to begin")
    print("="*50 + "\n")


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Run the dashboard server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
