from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import sqlite3
import secrets
import hashlib
import json
import os
import threading
from datetime import datetime
from typing import Optional
import httpx

# ============== CONFIG ==============
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
BOT_SECRET = os.getenv("BOT_SECRET", "bot_secret_key_123")
DB_PATH = os.getenv("DB_PATH", "data/config.db")

# ============== DATABASE ==============
db_lock = threading.Lock()

def get_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            key_value TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '🤖',
            description TEXT,
            provider TEXT NOT NULL,
            endpoint TEXT,
            model_name TEXT NOT NULL,
            category TEXT DEFAULT 'custom',
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 100,
            config TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    
    # Default settings
    defaults = {
        "default_model": "groq",
        "bot_prefix": ".",
        "rate_limit_ai": "5",
        "rate_limit_img": "15",
        "system_prompt": "You are a helpful AI assistant.",
        "max_memory_messages": "25",
        "memory_timeout_minutes": "30"
    }
    for k, v in defaults.items():
        conn.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
    
    conn.commit()
    conn.close()

# ============== APP ==============
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Bot Config Panel", lifespan=lifespan)
security = HTTPBasic()

# ============== AUTH ==============
def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, ADMIN_USER)
    correct_pass = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def verify_bot(request: Request):
    auth = request.headers.get("X-Bot-Secret", "")
    if not secrets.compare_digest(auth, BOT_SECRET):
        raise HTTPException(status_code=401, detail="Invalid bot secret")
    return True

def add_log(action: str, details: str = "", ip: str = ""):
    with db_lock:
        conn = get_db()
        conn.execute('INSERT INTO logs (action, details, ip) VALUES (?, ?, ?)', (action, details, ip))
        conn.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY created_at DESC LIMIT 500)')
        conn.commit()
        conn.close()

# ============== BOT API ENDPOINTS ==============
@app.get("/api/bot/keys")
async def bot_get_keys(request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches all enabled API keys"""
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT name, key_value FROM api_keys WHERE enabled = 1').fetchall()
        conn.close()
    return {row["name"]: row["key_value"] for row in rows}

@app.get("/api/bot/key/{name}")
async def bot_get_key(name: str, request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches specific API key"""
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT key_value FROM api_keys WHERE name = ? AND enabled = 1', (name,)).fetchone()
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": row["key_value"]}

@app.get("/api/bot/models")
async def bot_get_models(request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches all enabled models"""
    with db_lock:
        conn = get_db()
        rows = conn.execute('''
            SELECT model_id, name, emoji, description, provider, endpoint, model_name, category, config 
            FROM models WHERE enabled = 1 ORDER BY priority ASC
        ''').fetchall()
        conn.close()
    
    models = {}
    for row in rows:
        models[row["model_id"]] = {
            "e": row["emoji"],
            "n": row["name"],
            "d": row["description"] or "",
            "c": row["category"],
            "p": row["provider"],
            "m": row["model_name"],
            "endpoint": row["endpoint"] or "",
            "config": json.loads(row["config"] or "{}")
        }
    return models

@app.get("/api/bot/settings")
async def bot_get_settings(request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches all settings"""
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT key, value FROM settings').fetchall()
        conn.close()
    return {row["key"]: row["value"] for row in rows}

@app.get("/api/bot/setting/{key}")
async def bot_get_setting(key: str, request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches specific setting"""
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"value": row["value"]}

@app.get("/api/bot/config")
async def bot_get_full_config(request: Request, _: bool = Depends(verify_bot)):
    """Bot fetches complete configuration"""
    with db_lock:
        conn = get_db()
        keys = {row["name"]: row["key_value"] for row in conn.execute('SELECT name, key_value FROM api_keys WHERE enabled = 1').fetchall()}
        
        models = {}
        for row in conn.execute('SELECT * FROM models WHERE enabled = 1 ORDER BY priority ASC').fetchall():
            models[row["model_id"]] = {
                "e": row["emoji"], "n": row["name"], "d": row["description"] or "",
                "c": row["category"], "p": row["provider"], "m": row["model_name"],
                "endpoint": row["endpoint"] or "", "config": json.loads(row["config"] or "{}")
            }
        
        settings = {row["key"]: row["value"] for row in conn.execute('SELECT key, value FROM settings').fetchall()}
        conn.close()
    
    return {"keys": keys, "models": models, "settings": settings, "timestamp": datetime.now().isoformat()}

@app.post("/api/bot/ping")
async def bot_ping(request: Request, _: bool = Depends(verify_bot)):
    """Bot health check"""
    add_log("bot_ping", "", request.client.host if request.client else "")
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# ============== ADMIN API ENDPOINTS ==============
# --- API Keys ---
@app.get("/api/admin/keys")
async def admin_list_keys(user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT id, name, enabled, created_at, updated_at FROM api_keys ORDER BY name').fetchall()
        conn.close()
    return [dict(row) for row in rows]

@app.post("/api/admin/keys")
async def admin_add_key(request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    name = data.get("name", "").strip().lower()
    key_value = data.get("key", "").strip()
    
    if not name or not key_value:
        raise HTTPException(status_code=400, detail="Name and key required")
    
    with db_lock:
        conn = get_db()
        try:
            conn.execute('INSERT INTO api_keys (name, key_value) VALUES (?, ?)', (name, key_value))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=400, detail="Key name already exists")
        conn.close()
    
    add_log("add_key", f"Added key: {name}", request.client.host if request.client else "")
    return {"success": True, "message": f"Key '{name}' added"}

@app.put("/api/admin/keys/{key_id}")
async def admin_update_key(key_id: int, request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    key_value = data.get("key", "").strip()
    enabled = data.get("enabled")
    
    with db_lock:
        conn = get_db()
        if key_value:
            conn.execute('UPDATE api_keys SET key_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (key_value, key_id))
        if enabled is not None:
            conn.execute('UPDATE api_keys SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (1 if enabled else 0, key_id))
        conn.commit()
        conn.close()
    
    add_log("update_key", f"Updated key ID: {key_id}", request.client.host if request.client else "")
    return {"success": True}

@app.delete("/api/admin/keys/{key_id}")
async def admin_delete_key(key_id: int, request: Request, user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()
        conn.close()
    
    add_log("delete_key", f"Deleted key ID: {key_id}", request.client.host if request.client else "")
    return {"success": True}

# --- Models ---
@app.get("/api/admin/models")
async def admin_list_models(user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT * FROM models ORDER BY category, priority, name').fetchall()
        conn.close()
    return [dict(row) for row in rows]

@app.post("/api/admin/models")
async def admin_add_model(request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    required = ["model_id", "name", "provider", "model_name"]
    for field in required:
        if not data.get(field):
            raise HTTPException(status_code=400, detail=f"Field '{field}' required")
    
    with db_lock:
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO models (model_id, name, emoji, description, provider, endpoint, model_name, category, priority, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data["model_id"], data["name"], data.get("emoji", "🤖"),
                data.get("description", ""), data["provider"], data.get("endpoint", ""),
                data["model_name"], data.get("category", "custom"),
                data.get("priority", 100), json.dumps(data.get("config", {}))
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=400, detail="Model ID already exists")
        conn.close()
    
    add_log("add_model", f"Added model: {data['model_id']}", request.client.host if request.client else "")
    return {"success": True}

@app.put("/api/admin/models/{model_id}")
async def admin_update_model(model_id: int, request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    
    fields = []
    values = []
    for key in ["name", "emoji", "description", "provider", "endpoint", "model_name", "category", "priority", "enabled"]:
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key] if key != "config" else json.dumps(data[key]))
    
    if "config" in data:
        fields.append("config = ?")
        values.append(json.dumps(data["config"]))
    
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    values.append(model_id)
    
    with db_lock:
        conn = get_db()
        conn.execute(f'UPDATE models SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
        conn.close()
    
    add_log("update_model", f"Updated model ID: {model_id}", request.client.host if request.client else "")
    return {"success": True}

@app.delete("/api/admin/models/{model_id}")
async def admin_delete_model(model_id: int, request: Request, user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        conn.execute('DELETE FROM models WHERE id = ?', (model_id,))
        conn.commit()
        conn.close()
    
    add_log("delete_model", f"Deleted model ID: {model_id}", request.client.host if request.client else "")
    return {"success": True}

# --- Settings ---
@app.get("/api/admin/settings")
async def admin_list_settings(user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT * FROM settings ORDER BY key').fetchall()
        conn.close()
    return [dict(row) for row in rows]

@app.put("/api/admin/settings/{key}")
async def admin_update_setting(key: str, request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    value = data.get("value", "")
    
    with db_lock:
        conn = get_db()
        conn.execute('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)', (key, value))
        conn.commit()
        conn.close()
    
    add_log("update_setting", f"Updated: {key}", request.client.host if request.client else "")
    return {"success": True}

# --- Logs ---
@app.get("/api/admin/logs")
async def admin_list_logs(user: str = Depends(verify_admin)):
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT 100').fetchall()
        conn.close()
    return [dict(row) for row in rows]

# --- Test API Key ---
@app.post("/api/admin/test-key")
async def admin_test_key(request: Request, user: str = Depends(verify_admin)):
    data = await request.json()
    provider = data.get("provider", "")
    key = data.get("key", "")
    
    test_endpoints = {
        "groq": ("https://api.groq.com/openai/v1/models", "Bearer"),
        "openrouter": ("https://openrouter.ai/api/v1/models", "Bearer"),
        "cerebras": ("https://api.cerebras.ai/v1/models", "Bearer"),
        "together": ("https://api.together.xyz/v1/models", "Bearer"),
        "mistral": ("https://api.mistral.ai/v1/models", "Bearer"),
        "cohere": ("https://api.cohere.com/v1/models", "bearer"),
        "huggingface": ("https://huggingface.co/api/whoami-v2", "Bearer"),
    }
    
    if provider not in test_endpoints:
        return {"success": True, "message": "Cannot test this provider, assuming valid"}
    
    url, auth_type = test_endpoints[provider]
    
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"{auth_type} {key}"}
            resp = await client.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                return {"success": True, "message": "API key is valid"}
            elif resp.status_code == 401:
                return {"success": False, "message": "Invalid API key"}
            else:
                return {"success": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)[:100]}

# ============== WEB UI ==============
def get_html():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Config Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        :root { --primary: #5865F2; --dark: #1a1a2e; --darker: #16213e; --accent: #0f3460; }
        body { background: linear-gradient(135deg, var(--dark) 0%, var(--darker) 100%); min-height: 100vh; color: #fff; }
        .navbar { background: rgba(0,0,0,0.3) !important; backdrop-filter: blur(10px); }
        .card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 15px; }
        .card-header { background: rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.1); }
        .table { color: #fff; }
        .table-dark { background: transparent; }
        .table-dark td, .table-dark th { border-color: rgba(255,255,255,0.1); background: transparent; }
        .btn-primary { background: var(--primary); border: none; }
        .btn-primary:hover { background: #4752c4; }
        .form-control, .form-select { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: #fff; }
        .form-control:focus, .form-select:focus { background: rgba(255,255,255,0.15); border-color: var(--primary); color: #fff; box-shadow: 0 0 0 0.25rem rgba(88,101,242,0.25); }
        .form-control::placeholder { color: rgba(255,255,255,0.5); }
        .modal-content { background: var(--darker); border: 1px solid rgba(255,255,255,0.1); }
        .nav-pills .nav-link { color: rgba(255,255,255,0.7); }
        .nav-pills .nav-link.active { background: var(--primary); }
        .badge-enabled { background: #2ecc71; }
        .badge-disabled { background: #e74c3c; }
        .key-value { font-family: monospace; background: rgba(0,0,0,0.3); padding: 2px 8px; border-radius: 4px; }
        .stats-card { background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%); }
        .provider-icon { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; margin-right: 8px; }
        .toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; }
        .copy-btn { cursor: pointer; opacity: 0.7; }
        .copy-btn:hover { opacity: 1; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container">
            <a class="navbar-brand" href="#"><i class="bi bi-gear-fill me-2"></i>Bot Config Panel</a>
            <div class="navbar-nav ms-auto">
                <span class="nav-link" id="status-indicator"><i class="bi bi-circle-fill text-success me-1"></i> Connected</span>
            </div>
        </div>
    </nav>

    <div class="container pb-5">
        <ul class="nav nav-pills mb-4" id="mainTab" role="tablist">
            <li class="nav-item"><a class="nav-link active" data-bs-toggle="pill" href="#keys"><i class="bi bi-key me-1"></i> API Keys</a></li>
            <li class="nav-item"><a class="nav-link" data-bs-toggle="pill" href="#models"><i class="bi bi-robot me-1"></i> Models</a></li>
            <li class="nav-item"><a class="nav-link" data-bs-toggle="pill" href="#settings"><i class="bi bi-sliders me-1"></i> Settings</a></li>
            <li class="nav-item"><a class="nav-link" data-bs-toggle="pill" href="#logs"><i class="bi bi-list-ul me-1"></i> Logs</a></li>
        </ul>

        <div class="tab-content">
            <!-- API Keys Tab -->
            <div class="tab-pane fade show active" id="keys">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="bi bi-key me-2"></i>API Keys</h5>
                        <button class="btn btn-primary btn-sm" onclick="showAddKeyModal()"><i class="bi bi-plus-lg me-1"></i>Add Key</button>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-dark table-hover">
                                <thead><tr><th>Provider</th><th>Key</th><th>Status</th><th>Updated</th><th>Actions</th></tr></thead>
                                <tbody id="keys-table"></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Models Tab -->
            <div class="tab-pane fade" id="models">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="bi bi-robot me-2"></i>AI Models</h5>
                        <button class="btn btn-primary btn-sm" onclick="showAddModelModal()"><i class="bi bi-plus-lg me-1"></i>Add Model</button>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-dark table-hover">
                                <thead><tr><th>ID</th><th>Name</th><th>Provider</th><th>Model</th><th>Category</th><th>Status</th><th>Actions</th></tr></thead>
                                <tbody id="models-table"></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Settings Tab -->
            <div class="tab-pane fade" id="settings">
                <div class="card">
                    <div class="card-header"><h5 class="mb-0"><i class="bi bi-sliders me-2"></i>Bot Settings</h5></div>
                    <div class="card-body">
                        <form id="settings-form">
                            <div class="row g-3" id="settings-fields"></div>
                            <div class="mt-4">
                                <button type="submit" class="btn btn-primary"><i class="bi bi-save me-1"></i>Save All Settings</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>

            <!-- Logs Tab -->
            <div class="tab-pane fade" id="logs">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="bi bi-list-ul me-2"></i>Activity Logs</h5>
                        <button class="btn btn-outline-light btn-sm" onclick="loadLogs()"><i class="bi bi-arrow-clockwise"></i></button>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive" style="max-height: 500px; overflow-y: auto;">
                            <table class="table table-dark table-sm">
                                <thead><tr><th>Time</th><th>Action</th><th>Details</th><th>IP</th></tr></thead>
                                <tbody id="logs-table"></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Add Key Modal -->
    <div class="modal fade" id="addKeyModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header"><h5 class="modal-title"><i class="bi bi-key me-2"></i>Add API Key</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
                <form id="add-key-form">
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Provider Name</label>
                            <select class="form-select" id="key-name" required>
                                <option value="">Select provider...</option>
                                <option value="groq">Groq</option>
                                <option value="openrouter">OpenRouter</option>
                                <option value="cerebras">Cerebras</option>
                                <option value="sambanova">SambaNova</option>
                                <option value="cloudflare_account">Cloudflare Account ID</option>
                                <option value="cloudflare_token">Cloudflare Token</option>
                                <option value="cohere">Cohere</option>
                                <option value="mistral">Mistral</option>
                                <option value="together">Together</option>
                                <option value="moonshot">Moonshot</option>
                                <option value="huggingface">HuggingFace</option>
                                <option value="replicate">Replicate</option>
                                <option value="tavily">Tavily</option>
                                <option value="pollinations">Pollinations</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">API Key</label>
                            <input type="text" class="form-control" id="key-value" required placeholder="sk-xxxxx...">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-info" onclick="testKey()"><i class="bi bi-check-circle me-1"></i>Test</button>
                        <button type="submit" class="btn btn-primary"><i class="bi bi-plus-lg me-1"></i>Add</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Edit Key Modal -->
    <div class="modal fade" id="editKeyModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header"><h5 class="modal-title"><i class="bi bi-pencil me-2"></i>Edit API Key</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
                <form id="edit-key-form">
                    <div class="modal-body">
                        <input type="hidden" id="edit-key-id">
                        <div class="mb-3">
                            <label class="form-label">Provider</label>
                            <input type="text" class="form-control" id="edit-key-name" readonly>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">New API Key (leave blank to keep current)</label>
                            <input type="text" class="form-control" id="edit-key-value" placeholder="sk-xxxxx...">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-primary"><i class="bi bi-save me-1"></i>Save</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Add Model Modal -->
    <div class="modal fade" id="addModelModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header"><h5 class="modal-title"><i class="bi bi-robot me-2"></i>Add Model</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
                <form id="add-model-form">
                    <div class="modal-body">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Model ID</label>
                                <input type="text" class="form-control" id="model-id" required placeholder="my_custom_model">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Display Name</label>
                                <input type="text" class="form-control" id="model-name" required placeholder="My Model">
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Emoji</label>
                                <input type="text" class="form-control" id="model-emoji" value="🤖" maxlength="2">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Provider</label>
                                <select class="form-select" id="model-provider" required>
                                    <option value="groq">Groq</option>
                                    <option value="openrouter">OpenRouter</option>
                                    <option value="cerebras">Cerebras</option>
                                    <option value="sambanova">SambaNova</option>
                                    <option value="cloudflare">Cloudflare</option>
                                    <option value="cohere">Cohere</option>
                                    <option value="mistral">Mistral</option>
                                    <option value="together">Together</option>
                                    <option value="moonshot">Moonshot</option>
                                    <option value="huggingface">HuggingFace</option>
                                    <option value="replicate">Replicate</option>
                                    <option value="pollinations">Pollinations</option>
                                    <option value="tavily">Tavily</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Category</label>
                                <select class="form-select" id="model-category">
                                    <option value="main">Main</option>
                                    <option value="openrouter">OpenRouter</option>
                                    <option value="pollinations">Pollinations</option>
                                    <option value="custom">Custom</option>
                                </select>
                            </div>
                            <div class="col-md-8">
                                <label class="form-label">Model Name (API)</label>
                                <input type="text" class="form-control" id="model-model-name" required placeholder="llama-3.3-70b-versatile">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Priority</label>
                                <input type="number" class="form-control" id="model-priority" value="100">
                            </div>
                            <div class="col-12">
                                <label class="form-label">Custom Endpoint (optional)</label>
                                <input type="text" class="form-control" id="model-endpoint" placeholder="https://api.example.com/v1/chat/completions">
                            </div>
                            <div class="col-12">
                                <label class="form-label">Description</label>
                                <input type="text" class="form-control" id="model-description" placeholder="Fast and accurate">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-primary"><i class="bi bi-plus-lg me-1"></i>Add Model</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Edit Model Modal -->
    <div class="modal fade" id="editModelModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header"><h5 class="modal-title"><i class="bi bi-pencil me-2"></i>Edit Model</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
                <form id="edit-model-form">
                    <div class="modal-body">
                        <input type="hidden" id="edit-model-db-id">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Model ID</label>
                                <input type="text" class="form-control" id="edit-model-id" readonly>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Display Name</label>
                                <input type="text" class="form-control" id="edit-model-name" required>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Emoji</label>
                                <input type="text" class="form-control" id="edit-model-emoji" maxlength="2">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Provider</label>
                                <select class="form-select" id="edit-model-provider" required>
                                    <option value="groq">Groq</option>
                                    <option value="openrouter">OpenRouter</option>
                                    <option value="cerebras">Cerebras</option>
                                    <option value="sambanova">SambaNova</option>
                                    <option value="cloudflare">Cloudflare</option>
                                    <option value="cohere">Cohere</option>
                                    <option value="mistral">Mistral</option>
                                    <option value="together">Together</option>
                                    <option value="pollinations">Pollinations</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Category</label>
                                <select class="form-select" id="edit-model-category">
                                    <option value="main">Main</option>
                                    <option value="openrouter">OpenRouter</option>
                                    <option value="pollinations">Pollinations</option>
                                    <option value="custom">Custom</option>
                                </select>
                            </div>
                            <div class="col-md-8">
                                <label class="form-label">Model Name (API)</label>
                                <input type="text" class="form-control" id="edit-model-model-name" required>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Priority</label>
                                <input type="number" class="form-control" id="edit-model-priority">
                            </div>
                            <div class="col-12">
                                <label class="form-label">Custom Endpoint</label>
                                <input type="text" class="form-control" id="edit-model-endpoint">
                            </div>
                            <div class="col-12">
                                <label class="form-label">Description</label>
                                <input type="text" class="form-control" id="edit-model-description">
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-primary"><i class="bi bi-save me-1"></i>Save</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function showToast(message, type = 'success') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = `toast show bg-${type === 'success' ? 'success' : 'danger'} text-white`;
            toast.innerHTML = `<div class="toast-body d-flex justify-content-between align-items-center">${message}<button class="btn-close btn-close-white ms-2" onclick="this.parentElement.parentElement.remove()"></button></div>`;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        async function api(method, endpoint, data = null) {
            const options = { method, headers: { 'Content-Type': 'application/json' } };
            if (data) options.body = JSON.stringify(data);
            const resp = await fetch(`/api/admin${endpoint}`, options);
            if (resp.status === 401) { window.location.reload(); return null; }
            return resp.json();
        }

        // ===== KEYS =====
        async function loadKeys() {
            const keys = await api('GET', '/keys');
            const tbody = document.getElementById('keys-table');
            tbody.innerHTML = keys.map(k => `
                <tr>
                    <td><strong>${k.name}</strong></td>
                    <td><span class="key-value">••••••••${k.name.slice(-4)}</span></td>
                    <td><span class="badge ${k.enabled ? 'badge-enabled' : 'badge-disabled'}">${k.enabled ? 'Enabled' : 'Disabled'}</span></td>
                    <td>${new Date(k.updated_at).toLocaleDateString()}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-light me-1" onclick="toggleKey(${k.id}, ${!k.enabled})"><i class="bi bi-power"></i></button>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="showEditKeyModal(${k.id}, '${k.name}')"><i class="bi bi-pencil"></i></button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteKey(${k.id}, '${k.name}')"><i class="bi bi-trash"></i></button>
                    </td>
                </tr>
            `).join('');
        }

        function showAddKeyModal() {
            document.getElementById('add-key-form').reset();
            new bootstrap.Modal(document.getElementById('addKeyModal')).show();
        }

        document.getElementById('add-key-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const result = await api('POST', '/keys', {
                name: document.getElementById('key-name').value,
                key: document.getElementById('key-value').value
            });
            if (result.success) {
                showToast('API key added successfully');
                bootstrap.Modal.getInstance(document.getElementById('addKeyModal')).hide();
                loadKeys();
            } else {
                showToast(result.detail || 'Error adding key', 'error');
            }
        });

        function showEditKeyModal(id, name) {
            document.getElementById('edit-key-id').value = id;
            document.getElementById('edit-key-name').value = name;
            document.getElementById('edit-key-value').value = '';
            new bootstrap.Modal(document.getElementById('editKeyModal')).show();
        }

        document.getElementById('edit-key-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('edit-key-id').value;
            const key = document.getElementById('edit-key-value').value;
            if (key) {
                await api('PUT', `/keys/${id}`, { key });
                showToast('API key updated');
                bootstrap.Modal.getInstance(document.getElementById('editKeyModal')).hide();
                loadKeys();
            }
        });

        async function toggleKey(id, enabled) {
            await api('PUT', `/keys/${id}`, { enabled });
            loadKeys();
        }

        async function deleteKey(id, name) {
            if (confirm(`Delete API key "${name}"?`)) {
                await api('DELETE', `/keys/${id}`);
                showToast('API key deleted');
                loadKeys();
            }
        }

        async function testKey() {
            const provider = document.getElementById('key-name').value;
            const key = document.getElementById('key-value').value;
            if (!provider || !key) return showToast('Select provider and enter key', 'error');
            
            const result = await api('POST', '/test-key', { provider, key });
            showToast(result.message, result.success ? 'success' : 'error');
        }

        // ===== MODELS =====
        async function loadModels() {
            const models = await api('GET', '/models');
            const tbody = document.getElementById('models-table');
            tbody.innerHTML = models.map(m => `
                <tr>
                    <td><code>${m.model_id}</code></td>
                    <td>${m.emoji} ${m.name}</td>
                    <td>${m.provider}</td>
                    <td><small class="text-muted">${m.model_name.substring(0, 30)}...</small></td>
                    <td><span class="badge bg-secondary">${m.category}</span></td>
                    <td><span class="badge ${m.enabled ? 'badge-enabled' : 'badge-disabled'}">${m.enabled ? 'On' : 'Off'}</span></td>
                    <td>
                        <button class="btn btn-sm btn-outline-light me-1" onclick="toggleModel(${m.id}, ${!m.enabled})"><i class="bi bi-power"></i></button>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="showEditModelModal(${JSON.stringify(m).replace(/"/g, '&quot;')})"><i class="bi bi-pencil"></i></button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteModel(${m.id}, '${m.name}')"><i class="bi bi-trash"></i></button>
                    </td>
                </tr>
            `).join('');
        }

        function showAddModelModal() {
            document.getElementById('add-model-form').reset();
            document.getElementById('model-emoji').value = '🤖';
            document.getElementById('model-priority').value = 100;
            new bootstrap.Modal(document.getElementById('addModelModal')).show();
        }

        document.getElementById('add-model-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const result = await api('POST', '/models', {
                model_id: document.getElementById('model-id').value,
                name: document.getElementById('model-name').value,
                emoji: document.getElementById('model-emoji').value,
                provider: document.getElementById('model-provider').value,
                model_name: document.getElementById('model-model-name').value,
                category: document.getElementById('model-category').value,
                priority: parseInt(document.getElementById('model-priority').value),
                endpoint: document.getElementById('model-endpoint').value,
                description: document.getElementById('model-description').value
            });
            if (result.success) {
                showToast('Model added successfully');
                bootstrap.Modal.getInstance(document.getElementById('addModelModal')).hide();
                loadModels();
            } else {
                showToast(result.detail || 'Error adding model', 'error');
            }
        });

        function showEditModelModal(model) {
            document.getElementById('edit-model-db-id').value = model.id;
            document.getElementById('edit-model-id').value = model.model_id;
            document.getElementById('edit-model-name').value = model.name;
            document.getElementById('edit-model-emoji').value = model.emoji;
            document.getElementById('edit-model-provider').value = model.provider;
            document.getElementById('edit-model-model-name').value = model.model_name;
            document.getElementById('edit-model-category').value = model.category;
            document.getElementById('edit-model-priority').value = model.priority;
            document.getElementById('edit-model-endpoint').value = model.endpoint || '';
            document.getElementById('edit-model-description').value = model.description || '';
            new bootstrap.Modal(document.getElementById('editModelModal')).show();
        }

        document.getElementById('edit-model-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('edit-model-db-id').value;
            await api('PUT', `/models/${id}`, {
                name: document.getElementById('edit-model-name').value,
                emoji: document.getElementById('edit-model-emoji').value,
                provider: document.getElementById('edit-model-provider').value,
                model_name: document.getElementById('edit-model-model-name').value,
                category: document.getElementById('edit-model-category').value,
                priority: parseInt(document.getElementById('edit-model-priority').value),
                endpoint: document.getElementById('edit-model-endpoint').value,
                description: document.getElementById('edit-model-description').value
            });
            showToast('Model updated');
            bootstrap.Modal.getInstance(document.getElementById('editModelModal')).hide();
            loadModels();
        });

        async function toggleModel(id, enabled) {
            await api('PUT', `/models/${id}`, { enabled: enabled ? 1 : 0 });
            loadModels();
        }

        async function deleteModel(id, name) {
            if (confirm(`Delete model "${name}"?`)) {
                await api('DELETE', `/models/${id}`);
                showToast('Model deleted');
                loadModels();
            }
        }

        // ===== SETTINGS =====
        const settingsInfo = {
            default_model: { label: 'Default AI Model', type: 'text', help: 'Model ID for public users' },
            bot_prefix: { label: 'Bot Prefix', type: 'text', help: 'Command prefix (e.g., . or !)' },
            rate_limit_ai: { label: 'AI Rate Limit (seconds)', type: 'number', help: 'Cooldown between AI commands' },
            rate_limit_img: { label: 'Image Rate Limit (seconds)', type: 'number', help: 'Cooldown between image commands' },
            system_prompt: { label: 'System Prompt', type: 'textarea', help: 'Base instruction for AI' },
            max_memory_messages: { label: 'Max Memory Messages', type: 'number', help: 'How many messages to remember' },
            memory_timeout_minutes: { label: 'Memory Timeout (minutes)', type: 'number', help: 'How long to keep memory' }
        };

        async function loadSettings() {
            const settings = await api('GET', '/settings');
            const container = document.getElementById('settings-fields');
            container.innerHTML = settings.map(s => {
                const info = settingsInfo[s.key] || { label: s.key, type: 'text', help: '' };
                if (info.type === 'textarea') {
                    return `<div class="col-12"><label class="form-label">${info.label}</label><textarea class="form-control" name="${s.key}" rows="3">${s.value}</textarea><small class="text-muted">${info.help}</small></div>`;
                }
                return `<div class="col-md-6"><label class="form-label">${info.label}</label><input type="${info.type}" class="form-control" name="${s.key}" value="${s.value}"><small class="text-muted">${info.help}</small></div>`;
            }).join('');
        }

        document.getElementById('settings-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            for (const [key, value] of formData.entries()) {
                await api('PUT', `/settings/${key}`, { value });
            }
            showToast('Settings saved successfully');
        });

        // ===== LOGS =====
        async function loadLogs() {
            const logs = await api('GET', '/logs');
            const tbody = document.getElementById('logs-table');
            tbody.innerHTML = logs.map(l => `
                <tr>
                    <td><small>${new Date(l.created_at).toLocaleString()}</small></td>
                    <td><code>${l.action}</code></td>
                    <td><small>${l.details || '-'}</small></td>
                    <td><small class="text-muted">${l.ip || '-'}</small></td>
                </tr>
            `).join('');
        }

        // ===== INIT =====
        document.addEventListener('DOMContentLoaded', () => {
            loadKeys();
            loadModels();
            loadSettings();
            loadLogs();
        });

        // Tab change handlers
        document.querySelectorAll('[data-bs-toggle="pill"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const target = e.target.getAttribute('href');
                if (target === '#keys') loadKeys();
                else if (target === '#models') loadModels();
                else if (target === '#settings') loadSettings();
                else if (target === '#logs') loadLogs();
            });
        });
    </script>
</body>
</html>'''

@app.get("/", response_class=HTMLResponse)
async def web_ui(user: str = Depends(verify_admin)):
    return get_html()

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
