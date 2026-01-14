import os
import sys
import json
import time
import hashlib
import requests

print("=" * 50, flush=True)
print("🚀 Starting app.py...", flush=True)
print(f"Python: {sys.version}", flush=True)
print(f"PORT: {os.getenv('PORT', '8080')}", flush=True)
print("=" * 50, flush=True)

from functools import wraps
from flask import Flask, request, jsonify, render_template, make_response
from flask_cors import CORS

print("✅ Flask imported", flush=True)

# Import database with error handling
try:
    from database import Database
    print("✅ Database imported", flush=True)
except Exception as e:
    print(f"❌ Database import error: {e}", flush=True)
    # Create minimal database class if import fails
    class Database:
        def __init__(self, path="panel.db"):
            import sqlite3
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self._init_db()
        def _init_db(self):
            self.conn.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires_at TEXT);
            ''')
            self.conn.commit()
        def get_setting(self, k, d=None):
            r = self.conn.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
            return r[0] if r else d
        def set_setting(self, k, v):
            self.conn.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (k, str(v)))
            self.conn.commit()
        def get_all_settings(self):
            return {r[0]: r[1] for r in self.conn.execute('SELECT key, value FROM settings').fetchall()}
        def validate_session(self, t):
            if not t: return False
            r = self.conn.execute('SELECT 1 FROM sessions WHERE token=?', (t,)).fetchone()
            return r is not None
        def create_session(self):
            import secrets
            from datetime import datetime, timedelta
            t = secrets.token_urlsafe(32)
            exp = (datetime.now() + timedelta(days=1)).isoformat()
            self.conn.execute('INSERT INTO sessions VALUES(?,?)', (t, exp))
            self.conn.commit()
            return t
        def delete_session(self, t):
            self.conn.execute('DELETE FROM sessions WHERE token=?', (t,))
            self.conn.commit()
        def get_all_api_keys(self): return []
        def get_api_key(self, n): return None
        def add_api_key(self, n, k, p): return True, "OK"
        def update_api_key(self, *a, **k): pass
        def delete_api_key(self, i): pass
        def update_api_test_result(self, *a): pass
        def get_all_models(self): return []
        def get_enabled_models(self): return {}
        def add_model(self, *a): return True, "OK"
        def update_model(self, *a, **k): pass
        def delete_model(self, i): pass
        def set_default_model(self, m): pass
        def get_all_user_models(self): return {}
        def set_user_model(self, u, m): pass
        def delete_user_model(self, u): pass
        def add_activity_log(self, *a): pass
        def get_activity_logs(self, l=50): return []
        def get_test_logs(self, l=50): return []

app = Flask(__name__)
CORS(app, supports_credentials=True)

print("✅ Flask app created", flush=True)

# Configuration
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
BOT_SECRET = os.getenv("BOT_SECRET", "bot_secret_key")
PORT = int(os.getenv("PORT", 8080))

db = Database()
print("✅ Database initialized", flush=True)

# Initialize default password if not exists
if not db.get_setting('admin_password_hash'):
    default_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    db.set_setting('admin_password_hash', default_hash)
    print("✅ Default password set", flush=True)

# ==================== Helpers ====================

def verify_password(password):
    stored_hash = db.get_setting('admin_password_hash')
    if not stored_hash:
        stored_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('session_token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        if not db.validate_session(token):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def require_bot_secret(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        secret = request.headers.get('X-Bot-Secret', '')
        if secret != BOT_SECRET:
            return jsonify({'error': 'Invalid bot secret'}), 403
        return f(*args, **kwargs)
    return decorated

# ==================== Auth Routes ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    password = data.get('password', '')
    
    if verify_password(password):
        token = db.create_session()
        db.add_activity_log('Login', 'Admin logged in', request.remote_addr)
        response = make_response(jsonify({'success': True, 'token': token}))
        response.set_cookie('session_token', token, httponly=True, samesite='Lax', max_age=86400)
        return response
    
    return jsonify({'error': 'Invalid password'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    token = request.cookies.get('session_token')
    if token:
        db.delete_session(token)
    response = make_response(jsonify({'success': True}))
    response.delete_cookie('session_token')
    return response

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    token = request.cookies.get('session_token') or request.headers.get('Authorization', '').replace('Bearer ', '')
    return jsonify({'authenticated': db.validate_session(token)})

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data = request.get_json() or {}
    current = data.get('current', '')
    new = data.get('new', '')
    
    if not verify_password(current):
        return jsonify({'error': 'Current password is incorrect'}), 400
    
    if len(new) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    new_hash = hashlib.sha256(new.encode()).hexdigest()
    db.set_setting('admin_password_hash', new_hash)
    return jsonify({'success': True})

# ==================== Bot Integration API ====================

@app.route('/api/bot/config', methods=['GET'])
@require_bot_secret
def get_bot_config():
    api_keys = db.get_all_api_keys()
    keys_dict = {k['name']: k['key_value'] for k in api_keys if k.get('is_active')}
    
    return jsonify({
        'keys': keys_dict,
        'models': db.get_enabled_models(),
        'settings': {
            'default_model': db.get_setting('default_model', 'groq'),
            'system_prompt': db.get_setting('system_prompt', 'You are a helpful assistant.'),
            'max_memory_messages': db.get_setting('max_memory_messages', '25'),
            'memory_timeout_minutes': db.get_setting('memory_timeout_minutes', '30'),
        },
        'user_models': db.get_all_user_models()
    })

# ==================== API Keys Routes ====================

@app.route('/api/keys', methods=['GET'])
@require_auth
def get_keys():
    keys = db.get_all_api_keys()
    for k in keys:
        if k.get('key_value'):
            kv = k['key_value']
            k['key_masked'] = kv[:8] + '...' + kv[-4:] if len(kv) > 12 else '****'
    return jsonify(keys)

@app.route('/api/keys', methods=['POST'])
@require_auth
def add_key():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    key_value = data.get('key_value', '').strip()
    provider = data.get('provider', 'custom').strip()
    
    if not name or not key_value:
        return jsonify({'error': 'Name and key value are required'}), 400
    
    success, message = db.add_api_key(name, key_value, provider)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/keys/<int:key_id>', methods=['PUT'])
@require_auth
def update_key(key_id):
    data = request.get_json() or {}
    db.update_api_key(key_id, key_value=data.get('key_value'), is_active=data.get('is_active'))
    return jsonify({'success': True})

@app.route('/api/keys/<int:key_id>', methods=['DELETE'])
@require_auth
def delete_key(key_id):
    db.delete_api_key(key_id)
    return jsonify({'success': True})

@app.route('/api/keys/test/<string:name>', methods=['POST'])
@require_auth
def test_key(name):
    key = db.get_api_key(name)
    if not key:
        return jsonify({'error': 'Key not found'}), 404
    
    start_time = time.time()
    result = {'success': False, 'message': 'Test not implemented', 'time': 0}
    
    try:
        if name == 'groq':
            r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            result['message'] = 'Working!' if r.status_code == 200 else f'HTTP {r.status_code}'
        else:
            result['message'] = 'Provider test not implemented'
        
        result['time'] = round((time.time() - start_time) * 1000)
    except Exception as e:
        result['message'] = str(e)[:100]
        result['time'] = round((time.time() - start_time) * 1000)
    
    return jsonify(result)

# ==================== Models Routes ====================

@app.route('/api/models', methods=['GET'])
@require_auth
def get_models():
    return jsonify(db.get_all_models())

@app.route('/api/models', methods=['POST'])
@require_auth
def add_model():
    data = request.get_json() or {}
    success, message = db.add_model(
        data.get('id', ''), data.get('emoji', '🤖'), data.get('name', ''),
        data.get('description', ''), data.get('category', 'custom'),
        data.get('provider', ''), data.get('model_id', '')
    )
    if success:
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/models/<string:model_id>', methods=['PUT'])
@require_auth
def update_model(model_id):
    data = request.get_json() or {}
    db.update_model(model_id, **data)
    return jsonify({'success': True})

@app.route('/api/models/<string:model_id>', methods=['DELETE'])
@require_auth
def delete_model(model_id):
    db.delete_model(model_id)
    return jsonify({'success': True})

@app.route('/api/models/<string:model_id>/toggle', methods=['POST'])
@require_auth
def toggle_model(model_id):
    data = request.get_json() or {}
    db.update_model(model_id, is_enabled=1 if data.get('enabled') else 0)
    return jsonify({'success': True})

@app.route('/api/models/<string:model_id>/set-default', methods=['POST'])
@require_auth
def set_default_model(model_id):
    db.set_default_model(model_id)
    return jsonify({'success': True})

# ==================== User Models ====================

@app.route('/api/user-models', methods=['GET'])
@require_auth
def get_user_models():
    return jsonify(db.get_all_user_models())

@app.route('/api/user-models/<string:user_id>', methods=['PUT'])
@require_auth
def set_user_model(user_id):
    data = request.get_json() or {}
    db.set_user_model(user_id, data.get('model_id', ''))
    return jsonify({'success': True})

@app.route('/api/user-models/<string:user_id>', methods=['DELETE'])
@require_auth
def delete_user_model(user_id):
    db.delete_user_model(user_id)
    return jsonify({'success': True})

# ==================== Settings ====================

@app.route('/api/settings', methods=['GET'])
@require_auth
def get_settings():
    settings = db.get_all_settings()
    settings.pop('admin_password_hash', None)
    return jsonify(settings)

@app.route('/api/settings', methods=['PUT'])
@require_auth
def update_settings():
    data = request.get_json() or {}
    for key, value in data.items():
        if key != 'admin_password_hash':
            db.set_setting(key, value)
    return jsonify({'success': True})

# ==================== Logs ====================

@app.route('/api/logs/activity', methods=['GET'])
@require_auth
def get_activity_logs():
    return jsonify(db.get_activity_logs(50))

@app.route('/api/logs/tests', methods=['GET'])
@require_auth
def get_test_logs():
    return jsonify(db.get_test_logs(50))

# ==================== Stats ====================

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    api_keys = db.get_all_api_keys()
    models = db.get_all_models()
    return jsonify({
        'total_keys': len(api_keys),
        'active_keys': len([k for k in api_keys if k.get('is_active')]),
        'total_models': len(models),
        'enabled_models': len([m for m in models if m.get('is_enabled')]),
        'default_model': db.get_setting('default_model', 'groq'),
        'user_models_count': len(db.get_all_user_models())
    })

# ==================== Health ====================

@app.route('/api/keepalive', methods=['GET'])
def keepalive():
    return jsonify({'status': 'ok', 'time': time.time()})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

# ==================== Frontend ====================

@app.route('/')
def index():
    try:
        return render_template('index.html')
    except Exception as e:
        # Fallback if template not found
        return f'''<!DOCTYPE html>
<html>
<head><title>AI Bot Panel</title>
<style>
body {{ font-family: Arial; background: #1a1a2e; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
.box {{ background: #16162a; padding: 40px; border-radius: 16px; text-align: center; }}
input {{ padding: 12px; margin: 10px 0; width: 200px; border-radius: 8px; border: 1px solid #333; background: #0f0f1a; color: white; }}
button {{ padding: 12px 24px; background: #6366f1; color: white; border: none; border-radius: 8px; cursor: pointer; }}
button:hover {{ background: #4f46e5; }}
</style>
</head>
<body>
<div class="box">
<h1>🤖 AI Bot Panel</h1>
<p>Login to continue</p>
<form id="f">
<input type="password" id="p" placeholder="Password" required><br>
<button type="submit">Login</button>
</form>
<p id="e" style="color:red"></p>
<script>
document.getElementById('f').onsubmit=async(e)=>{{
e.preventDefault();
const r=await fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password:document.getElementById('p').value}}),credentials:'include'}});
if(r.ok)location.reload();else document.getElementById('e').textContent='Invalid password';
}};
</script>
</div>
</body>
</html>'''

print("✅ All routes registered", flush=True)

# ==================== Run ====================

if __name__ == '__main__':
    print("=" * 50, flush=True)
    print(f"🌐 Starting server on port {PORT}", flush=True)
    print("=" * 50, flush=True)
    app.run(host='0.0.0.0', port=PORT, debug=False)