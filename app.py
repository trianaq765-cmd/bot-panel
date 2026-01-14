import os
import json
import time
import hashlib
import secrets
import requests as req
from datetime import datetime
from functools import wraps
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from database import Database

app = FastAPI(title="AI Bot Panel")

# Configuration
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
BOT_SECRET = os.getenv("BOT_SECRET", "bot_secret_key")

db = Database()
templates = Jinja2Templates(directory="templates")

# ==================== Models ====================
class LoginRequest(BaseModel):
    password: str

class ApiKeyRequest(BaseModel):
    name: str
    key_value: str
    provider: str = "custom"

class ApiKeyUpdate(BaseModel):
    key_value: Optional[str] = None
    is_active: Optional[bool] = None

class ModelRequest(BaseModel):
    id: str
    emoji: str = "🤖"
    name: str
    description: str = ""
    category: str = "custom"
    provider: str
    model_id: str

class ModelUpdate(BaseModel):
    emoji: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    model_id: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None

class UserModelRequest(BaseModel):
    model_id: str

class ToggleRequest(BaseModel):
    enabled: bool

class PasswordChange(BaseModel):
    current: str
    new: str

# ==================== Helpers ====================
def verify_password(password: str) -> bool:
    stored_hash = db.get_setting('admin_password_hash')
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

def get_session_token(request: Request) -> Optional[str]:
    return request.cookies.get('session_token') or request.headers.get('Authorization', '').replace('Bearer ', '')

def require_auth(request: Request):
    token = get_session_token(request)
    if not db.validate_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

def require_bot_secret(request: Request):
    secret = request.headers.get('X-Bot-Secret', '')
    if secret != BOT_SECRET:
        raise HTTPException(status_code=403, detail="Invalid bot secret")
    return True

# ==================== Auth Routes ====================
@app.post("/api/auth/login")
async def login(data: LoginRequest, response: Response):
    if verify_password(data.password):
        token = db.create_session()
        db.add_activity_log('Login', 'Admin logged in', None)
        response.set_cookie(key='session_token', value=token, httponly=True, samesite='lax', max_age=86400)
        return {"success": True, "token": token}
    
    db.add_activity_log('Login Failed', 'Invalid password attempt', None)
    raise HTTPException(status_code=401, detail="Invalid password")

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get('session_token')
    if token:
        db.delete_session(token)
    response.delete_cookie('session_token')
    return {"success": True}

@app.get("/api/auth/check")
async def check_auth(request: Request):
    token = get_session_token(request)
    return {"authenticated": db.validate_session(token)}

@app.post("/api/auth/change-password")
async def change_password(data: PasswordChange, auth: bool = Depends(require_auth)):
    if not verify_password(data.current):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    if len(data.new) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    new_hash = hashlib.sha256(data.new.encode()).hexdigest()
    db.set_setting('admin_password_hash', new_hash)
    db.add_activity_log('Password Changed', None, None)
    return {"success": True}

# ==================== Bot Integration API ====================
@app.get("/api/bot/config")
async def get_bot_config(request: Request, auth: bool = Depends(require_bot_secret)):
    api_keys = db.get_all_api_keys()
    keys_dict = {k['name']: k['key_value'] for k in api_keys if k['is_active']}
    
    return {
        'keys': keys_dict,
        'models': db.get_enabled_models(),
        'settings': {
            'default_model': db.get_setting('default_model', 'groq'),
            'system_prompt': db.get_setting('system_prompt'),
            'max_memory_messages': db.get_setting('max_memory_messages', '25'),
            'memory_timeout_minutes': db.get_setting('memory_timeout_minutes', '30'),
            'rate_limit_ai': db.get_setting('rate_limit_ai', '5'),
            'rate_limit_img': db.get_setting('rate_limit_img', '15'),
            'rate_limit_dump': db.get_setting('rate_limit_dump', '10'),
        },
        'user_models': db.get_all_user_models()
    }

# ==================== API Keys Routes ====================
@app.get("/api/keys")
async def get_keys(auth: bool = Depends(require_auth)):
    keys = db.get_all_api_keys()
    for k in keys:
        if k['key_value']:
            k['key_masked'] = k['key_value'][:8] + '...' + k['key_value'][-4:] if len(k['key_value']) > 12 else '****'
    return keys

@app.post("/api/keys")
async def add_key(data: ApiKeyRequest, request: Request, auth: bool = Depends(require_auth)):
    if not data.name or not data.key_value:
        raise HTTPException(status_code=400, detail="Name and key value are required")
    
    success, message = db.add_api_key(data.name, data.key_value, data.provider)
    if success:
        db.add_activity_log('API Key Added', f'Added key: {data.name}', request.client.host)
        return {"success": True, "message": message}
    raise HTTPException(status_code=400, detail=message)

@app.put("/api/keys/{key_id}")
async def update_key(key_id: int, data: ApiKeyUpdate, request: Request, auth: bool = Depends(require_auth)):
    db.update_api_key(key_id, key_value=data.key_value, is_active=data.is_active)
    db.add_activity_log('API Key Updated', f'Updated key ID: {key_id}', request.client.host)
    return {"success": True}

@app.delete("/api/keys/{key_id}")
async def delete_key(key_id: int, request: Request, auth: bool = Depends(require_auth)):
    db.delete_api_key(key_id)
    db.add_activity_log('API Key Deleted', f'Deleted key ID: {key_id}', request.client.host)
    return {"success": True}

@app.post("/api/keys/test/{name}")
async def test_key(name: str, request: Request, auth: bool = Depends(require_auth)):
    key = db.get_api_key(name)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found or inactive")
    
    start_time = time.time()
    result = {'success': False, 'message': '', 'time': 0}
    
    try:
        if name == 'groq':
            r = req.post('https://api.groq.com/openai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'cerebras':
            r = req.post('https://api.cerebras.ai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'llama-3.3-70b', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'openrouter':
            r = req.post('https://openrouter.ai/api/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'meta-llama/llama-3.3-70b-instruct:free', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'gemini':
            r = req.post(f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={key}',
                        headers={'Content-Type': 'application/json'},
                        json={'contents': [{'parts': [{'text': 'Hi'}]}]},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'mistral':
            r = req.post('https://api.mistral.ai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'mistral-small-latest', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'together':
            r = req.post('https://api.together.xyz/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'cohere':
            r = req.post('https://api.cohere.com/v1/chat',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'command-r-plus-08-2024', 'message': 'Hi'},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'sambanova':
            r = req.post('https://api.sambanova.ai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        json={'model': 'Meta-Llama-3.3-70B-Instruct', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                        timeout=15)
            result['success'] = r.status_code == 200
        elif name == 'tavily':
            r = req.post('https://api.tavily.com/search',
                        json={'api_key': key, 'query': 'test', 'max_results': 1},
                        timeout=15)
            result['success'] = r.status_code == 200
        else:
            result['message'] = 'Unknown provider - manual test required'
            result['success'] = None
        
        result['time'] = round((time.time() - start_time) * 1000)
        result['message'] = 'Working!' if result['success'] else 'Failed'
        
    except Exception as e:
        result['message'] = str(e)[:100]
        result['time'] = round((time.time() - start_time) * 1000)
    
    status = 'success' if result['success'] else 'failed' if result['success'] is False else 'unknown'
    db.update_api_test_result(name, status, result['time'], result['message'] if not result['success'] else None)
    db.add_activity_log('API Test', f'{name}: {status}', request.client.host)
    
    return result

# ==================== Models Routes ====================
@app.get("/api/models")
async def get_models(auth: bool = Depends(require_auth)):
    return db.get_all_models()

@app.post("/api/models")
async def add_model(data: ModelRequest, request: Request, auth: bool = Depends(require_auth)):
    success, message = db.add_model(
        data.id, data.emoji, data.name,
        data.description, data.category,
        data.provider, data.model_id
    )
    
    if success:
        db.add_activity_log('Model Added', f'Added: {data.id}', request.client.host)
        return {"success": True}
    raise HTTPException(status_code=400, detail=message)

@app.put("/api/models/{model_id}")
async def update_model(model_id: str, data: ModelUpdate, request: Request, auth: bool = Depends(require_auth)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    db.update_model(model_id, **update_data)
    db.add_activity_log('Model Updated', f'Updated: {model_id}', request.client.host)
    return {"success": True}

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str, request: Request, auth: bool = Depends(require_auth)):
    db.delete_model(model_id)
    db.add_activity_log('Model Deleted', f'Deleted: {model_id}', request.client.host)
    return {"success": True}

@app.post("/api/models/{model_id}/toggle")
async def toggle_model(model_id: str, data: ToggleRequest, auth: bool = Depends(require_auth)):
    db.update_model(model_id, is_enabled=1 if data.enabled else 0)
    return {"success": True}

@app.post("/api/models/{model_id}/set-default")
async def set_default_model(model_id: str, request: Request, auth: bool = Depends(require_auth)):
    db.set_default_model(model_id)
    db.add_activity_log('Default Model Changed', f'Set default: {model_id}', request.client.host)
    return {"success": True}

# ==================== User Models Routes ====================
@app.get("/api/user-models")
async def get_user_models(auth: bool = Depends(require_auth)):
    return db.get_all_user_models()

@app.put("/api/user-models/{user_id}")
async def set_user_model(user_id: str, data: UserModelRequest, auth: bool = Depends(require_auth)):
    db.set_user_model(user_id, data.model_id)
    return {"success": True}

@app.delete("/api/user-models/{user_id}")
async def delete_user_model(user_id: str, auth: bool = Depends(require_auth)):
    db.delete_user_model(user_id)
    return {"success": True}

# ==================== Settings Routes ====================
@app.get("/api/settings")
async def get_settings(auth: bool = Depends(require_auth)):
    settings = db.get_all_settings()
    settings.pop('admin_password_hash', None)
    return settings

@app.put("/api/settings")
async def update_settings(request: Request, auth: bool = Depends(require_auth)):
    data = await request.json()
    for key, value in data.items():
        if key != 'admin_password_hash':
            db.set_setting(key, value)
    db.add_activity_log('Settings Updated', None, request.client.host)
    return {"success": True}

# ==================== Logs Routes ====================
@app.get("/api/logs/activity")
async def get_activity_logs(limit: int = 50, auth: bool = Depends(require_auth)):
    return db.get_activity_logs(limit)

@app.get("/api/logs/tests")
async def get_test_logs(limit: int = 50, auth: bool = Depends(require_auth)):
    return db.get_test_logs(limit)

# ==================== Dashboard Stats ====================
@app.get("/api/stats")
async def get_stats(auth: bool = Depends(require_auth)):
    api_keys = db.get_all_api_keys()
    models = db.get_all_models()
    
    return {
        'total_keys': len(api_keys),
        'active_keys': len([k for k in api_keys if k['is_active']]),
        'total_models': len(models),
        'enabled_models': len([m for m in models if m['is_enabled']]),
        'default_model': db.get_setting('default_model', 'groq'),
        'user_models_count': len(db.get_all_user_models())
    }

# ==================== Health Check ====================
@app.get("/api/keepalive")
async def keepalive():
    return {"status": "ok", "time": time.time()}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ==================== Frontend ====================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ==================== Startup ====================
@app.on_event("startup")
async def startup():
    print("=" * 50)
    print(f"🌐 AI Bot Panel Started")
    print(f"🔑 Admin Key: {ADMIN_KEY}")
    print(f"🤖 Bot Secret: {BOT_SECRET[:10]}...")
    print("=" * 50)
