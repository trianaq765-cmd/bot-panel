import os
import sys
import time
import hashlib
import requests as req

print("=" * 50, flush=True)
print("🚀 Starting AI Bot Panel...", flush=True)
print(f"PORT: {os.getenv('PORT', '8080')}", flush=True)
print("=" * 50, flush=True)

from functools import wraps
from flask import Flask, request, jsonify, render_template_string, make_response
from flask_cors import CORS
from database import Database

app = Flask(__name__)
CORS(app, supports_credentials=True)

ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
BOT_SECRET = os.getenv("BOT_SECRET", "bot_secret_key")
PORT = int(os.getenv("PORT", 8080))

db = Database()
print("✅ Database initialized", flush=True)

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

# ==================== Auth ====================

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
    if not verify_password(data.get('current', '')):
        return jsonify({'error': 'Current password is incorrect'}), 400
    if len(data.get('new', '')) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    db.set_setting('admin_password_hash', hashlib.sha256(data['new'].encode()).hexdigest())
    return jsonify({'success': True})

# ==================== Bot API ====================

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

# ==================== API Keys ====================

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
        db.add_activity_log('API Key Added', f'Added: {name}', request.remote_addr)
        return jsonify({'success': True})
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
        return jsonify({'error': 'Key not found', 'success': False}), 404
    
    start = time.time()
    result = {'success': False, 'message': 'Unknown provider', 'time': 0}
    
    try:
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        payload = {'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5}
        
        endpoints = {
            'groq': ('https://api.groq.com/openai/v1/chat/completions', {**payload, 'model': 'llama-3.3-70b-versatile'}),
            'cerebras': ('https://api.cerebras.ai/v1/chat/completions', {**payload, 'model': 'llama-3.3-70b'}),
            'openrouter': ('https://openrouter.ai/api/v1/chat/completions', {**payload, 'model': 'meta-llama/llama-3.3-70b-instruct:free'}),
            'mistral': ('https://api.mistral.ai/v1/chat/completions', {**payload, 'model': 'mistral-small-latest'}),
            'together': ('https://api.together.xyz/v1/chat/completions', {**payload, 'model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo'}),
            'sambanova': ('https://api.sambanova.ai/v1/chat/completions', {**payload, 'model': 'Meta-Llama-3.3-70B-Instruct'}),
        }
        
        if name in endpoints:
            url, body = endpoints[name]
            r = req.post(url, headers=headers, json=body, timeout=15)
            result['success'] = r.status_code == 200
            result['message'] = 'Working!' if r.status_code == 200 else f'HTTP {r.status_code}'
        elif name == 'gemini':
            r = req.post(f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={key}',
                        json={'contents': [{'parts': [{'text': 'Hi'}]}]}, timeout=15)
            result['success'] = r.status_code == 200
            result['message'] = 'Working!' if r.status_code == 200 else f'HTTP {r.status_code}'
        elif name == 'cohere':
            r = req.post('https://api.cohere.com/v1/chat', headers=headers,
                        json={'model': 'command-r-plus-08-2024', 'message': 'Hi'}, timeout=15)
            result['success'] = r.status_code == 200
            result['message'] = 'Working!' if r.status_code == 200 else f'HTTP {r.status_code}'
        elif name == 'tavily':
            r = req.post('https://api.tavily.com/search', json={'api_key': key, 'query': 'test', 'max_results': 1}, timeout=15)
            result['success'] = r.status_code == 200
            result['message'] = 'Working!' if r.status_code == 200 else f'HTTP {r.status_code}'
        
        result['time'] = round((time.time() - start) * 1000)
    except Exception as e:
        result['message'] = str(e)[:100]
        result['time'] = round((time.time() - start) * 1000)
    
    status = 'success' if result['success'] else 'failed'
    db.update_api_test_result(name, status, result['time'], None if result['success'] else result['message'])
    return jsonify(result)

# ==================== Models ====================

@app.route('/api/models', methods=['GET'])
@require_auth
def get_models():
    return jsonify(db.get_all_models())

@app.route('/api/models', methods=['POST'])
@require_auth
def add_model():
    data = request.get_json() or {}
    required = ['id', 'name', 'provider', 'model_id']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'{f} is required'}), 400
    
    success, msg = db.add_model(
        data['id'], data.get('emoji', '🤖'), data['name'],
        data.get('description', ''), data.get('category', 'custom'),
        data['provider'], data['model_id']
    )
    if success:
        db.add_activity_log('Model Added', f"Added: {data['id']}", request.remote_addr)
        return jsonify({'success': True})
    return jsonify({'error': msg}), 400

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
    db.add_activity_log('Default Model Changed', f'Set: {model_id}', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/models/reset', methods=['POST'])
@require_auth
def reset_models():
    db.reset_models()
    db.add_activity_log('Models Reset', 'Reset to defaults', request.remote_addr)
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
    if not data.get('model_id'):
        return jsonify({'error': 'model_id required'}), 400
    db.set_user_model(user_id, data['model_id'])
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
    for k, v in data.items():
        if k != 'admin_password_hash':
            db.set_setting(k, v)
    db.add_activity_log('Settings Updated', None, request.remote_addr)
    return jsonify({'success': True})

# ==================== Logs & Stats ====================

@app.route('/api/logs/activity', methods=['GET'])
@require_auth
def get_activity_logs():
    return jsonify(db.get_activity_logs(50))

@app.route('/api/logs/tests', methods=['GET'])
@require_auth
def get_test_logs():
    return jsonify(db.get_test_logs(50))

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    keys = db.get_all_api_keys()
    models = db.get_all_models()
    return jsonify({
        'total_keys': len(keys),
        'active_keys': len([k for k in keys if k.get('is_active')]),
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

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Bot Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * { scrollbar-width: thin; scrollbar-color: #6366f1 #1e1e2e; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #1e1e2e; }
        ::-webkit-scrollbar-thumb { background: #6366f1; border-radius: 3px; }
        .glass { background: rgba(30, 30, 46, 0.9); backdrop-filter: blur(10px); }
        .fade-in { animation: fadeIn 0.2s ease-out; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .sidebar-open { transform: translateX(0); }
        .sidebar-closed { transform: translateX(-100%); }
        @media (min-width: 768px) { .sidebar-closed { transform: translateX(0); } }
    </style>
</head>
<body class="bg-[#0f0f1a] text-gray-100 min-h-screen">
    <div id="app">
        <!-- Login -->
        <div id="loginScreen" class="fixed inset-0 flex items-center justify-center bg-[#0f0f1a] z-50">
            <div class="glass rounded-2xl p-8 w-full max-w-sm border border-gray-700">
                <div class="text-center mb-6">
                    <div class="w-14 h-14 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center mx-auto mb-3 text-2xl">🤖</div>
                    <h1 class="text-xl font-bold">AI Bot Panel</h1>
                </div>
                <form id="loginForm">
                    <input type="password" id="loginPassword" placeholder="Password" class="w-full px-4 py-3 bg-[#1e1e2e] border border-gray-600 rounded-xl mb-4 outline-none focus:border-indigo-500">
                    <button type="submit" class="w-full py-3 bg-indigo-600 rounded-xl font-medium hover:bg-indigo-700">Login</button>
                    <p id="loginError" class="text-red-400 text-center text-sm mt-3 hidden"></p>
                </form>
            </div>
        </div>

        <!-- Main App -->
        <div id="mainApp" class="hidden">
            <!-- Mobile Header -->
            <header class="md:hidden fixed top-0 left-0 right-0 z-40 glass border-b border-gray-700 px-4 py-3 flex items-center justify-between">
                <button onclick="toggleSidebar()" class="p-2 hover:bg-gray-700 rounded-lg">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/></svg>
                </button>
                <span class="font-semibold" id="mobileTitle">Dashboard</span>
                <div class="w-10"></div>
            </header>

            <!-- Sidebar -->
            <aside id="sidebar" class="fixed md:static inset-y-0 left-0 z-50 w-64 bg-[#1e1e2e] border-r border-gray-700 flex flex-col transition-transform duration-200 sidebar-closed md:sidebar-open">
                <div class="p-4 border-b border-gray-700 flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="text-2xl">🤖</span>
                        <span class="font-bold">AI Panel</span>
                    </div>
                    <button onclick="toggleSidebar()" class="md:hidden p-1 hover:bg-gray-700 rounded">✕</button>
                </div>
                <nav class="flex-1 p-3 space-y-1">
                    <button onclick="showPage('dashboard')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="dashboard">📊 Dashboard</button>
                    <button onclick="showPage('keys')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="keys">🔑 API Keys</button>
                    <button onclick="showPage('models')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="models">🤖 AI Models</button>
                    <button onclick="showPage('users')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="users">👥 User Models</button>
                    <button onclick="showPage('settings')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="settings">⚙️ Settings</button>
                    <button onclick="showPage('logs')" class="nav-btn w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-gray-700" data-page="logs">📋 Logs</button>
                </nav>
                <div class="p-3 border-t border-gray-700">
                    <button onclick="doLogout()" class="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-red-400 hover:bg-red-500/10">🚪 Logout</button>
                </div>
            </aside>

            <!-- Overlay -->
            <div id="sidebarOverlay" class="fixed inset-0 bg-black/50 z-40 hidden md:hidden" onclick="toggleSidebar()"></div>

            <!-- Content -->
            <main class="md:ml-64 min-h-screen pt-14 md:pt-0">
                <div class="p-4 md:p-6">
                    <!-- Dashboard -->
                    <div id="page-dashboard" class="page fade-in">
                        <h2 class="text-xl font-bold mb-4">📊 Dashboard</h2>
                        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <p class="text-gray-400 text-sm">API Keys</p>
                                <p class="text-2xl font-bold" id="stat-keys">0</p>
                            </div>
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <p class="text-gray-400 text-sm">AI Models</p>
                                <p class="text-2xl font-bold" id="stat-models">0</p>
                            </div>
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <p class="text-gray-400 text-sm">Default</p>
                                <p class="text-lg font-bold truncate" id="stat-default">-</p>
                            </div>
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <p class="text-gray-400 text-sm">Users</p>
                                <p class="text-2xl font-bold" id="stat-users">0</p>
                            </div>
                        </div>
                        <div class="glass rounded-xl p-4 border border-gray-700">
                            <h3 class="font-semibold mb-3">Quick Actions</h3>
                            <div class="flex flex-wrap gap-2">
                                <button onclick="showPage('keys')" class="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-700">+ Add API Key</button>
                                <button onclick="showPage('models')" class="px-4 py-2 bg-purple-600 rounded-lg hover:bg-purple-700">Manage Models</button>
                                <button onclick="resetModels()" class="px-4 py-2 bg-orange-600 rounded-lg hover:bg-orange-700">Reset Models</button>
                            </div>
                        </div>
                    </div>

                    <!-- API Keys -->
                    <div id="page-keys" class="page hidden fade-in">
                        <div class="flex items-center justify-between mb-4">
                            <h2 class="text-xl font-bold">🔑 API Keys</h2>
                            <button onclick="showAddKeyModal()" class="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-700">+ Add</button>
                        </div>
                        <div id="keysList" class="grid gap-3"></div>
                    </div>

                    <!-- Models -->
                    <div id="page-models" class="page hidden fade-in">
                        <div class="flex items-center justify-between mb-4">
                            <h2 class="text-xl font-bold">🤖 AI Models</h2>
                            <button onclick="showAddModelModal()" class="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-700">+ Add</button>
                        </div>
                        <div class="mb-4 flex flex-wrap gap-2">
                            <button onclick="filterModels('all')" class="filter-btn px-3 py-1 rounded-lg bg-indigo-600 text-sm" data-filter="all">All</button>
                            <button onclick="filterModels('main')" class="filter-btn px-3 py-1 rounded-lg bg-gray-700 text-sm" data-filter="main">Main</button>
                            <button onclick="filterModels('gemini')" class="filter-btn px-3 py-1 rounded-lg bg-gray-700 text-sm" data-filter="gemini">Gemini</button>
                            <button onclick="filterModels('openrouter')" class="filter-btn px-3 py-1 rounded-lg bg-gray-700 text-sm" data-filter="openrouter">OpenRouter</button>
                            <button onclick="filterModels('pollinations')" class="filter-btn px-3 py-1 rounded-lg bg-gray-700 text-sm" data-filter="pollinations">Pollinations</button>
                        </div>
                        <div id="modelsList" class="space-y-2"></div>
                    </div>

                    <!-- User Models -->
                    <div id="page-users" class="page hidden fade-in">
                        <div class="flex items-center justify-between mb-4">
                            <h2 class="text-xl font-bold">👥 User Models</h2>
                            <button onclick="showAddUserModal()" class="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-700">+ Add</button>
                        </div>
                        <div id="usersList" class="space-y-2"></div>
                        <p class="text-gray-400 text-sm mt-4">💡 Assign specific AI models to Discord users by their User ID.</p>
                    </div>

                    <!-- Settings -->
                    <div id="page-settings" class="page hidden fade-in">
                        <h2 class="text-xl font-bold mb-4">⚙️ Settings</h2>
                        <div class="space-y-4 max-w-2xl">
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <label class="block text-sm text-gray-400 mb-2">System Prompt</label>
                                <textarea id="set-system_prompt" rows="3" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg outline-none"></textarea>
                            </div>
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <label class="block text-sm text-gray-400 mb-2">Max Memory Messages</label>
                                <input type="number" id="set-max_memory_messages" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg outline-none">
                            </div>
                            <div class="glass rounded-xl p-4 border border-gray-700">
                                <label class="block text-sm text-gray-400 mb-2">Memory Timeout (minutes)</label>
                                <input type="number" id="set-memory_timeout_minutes" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg outline-none">
                            </div>
                            <button onclick="saveSettings()" class="px-6 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-700">Save Settings</button>
                        </div>
                    </div>

                    <!-- Logs -->
                    <div id="page-logs" class="page hidden fade-in">
                        <h2 class="text-xl font-bold mb-4">📋 Activity Logs</h2>
                        <div id="logsList" class="space-y-2"></div>
                    </div>
                </div>
            </main>
        </div>

        <!-- Modal -->
        <div id="modal" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/60 p-4">
            <div class="glass rounded-xl border border-gray-700 w-full max-w-md max-h-[90vh] overflow-y-auto" id="modalContent"></div>
        </div>
    </div>

    <script>
        let models = [], keys = [], userModels = {}, currentFilter = 'all';

        // Auth
        async function checkAuth() {
            try {
                const r = await fetch('/api/auth/check', {credentials:'include'});
                const d = await r.json();
                if (d.authenticated) { showApp(); loadDashboard(); }
            } catch(e) {}
        }

        document.getElementById('loginForm').onsubmit = async (e) => {
            e.preventDefault();
            const r = await fetch('/api/auth/login', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: document.getElementById('loginPassword').value})
            });
            if (r.ok) { showApp(); loadDashboard(); }
            else { document.getElementById('loginError').textContent = 'Invalid password'; document.getElementById('loginError').classList.remove('hidden'); }
        };

        async function doLogout() {
            await fetch('/api/auth/logout', {method:'POST', credentials:'include'});
            location.reload();
        }

        function showApp() {
            document.getElementById('loginScreen').classList.add('hidden');
            document.getElementById('mainApp').classList.remove('hidden');
        }

        // Sidebar
        function toggleSidebar() {
            const s = document.getElementById('sidebar');
            const o = document.getElementById('sidebarOverlay');
            s.classList.toggle('sidebar-open');
            s.classList.toggle('sidebar-closed');
            o.classList.toggle('hidden');
        }

        // Navigation
        function showPage(page) {
            document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
            document.getElementById('page-' + page).classList.remove('hidden');
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('bg-indigo-600'));
            document.querySelector('[data-page="' + page + '"]')?.classList.add('bg-indigo-600');
            document.getElementById('mobileTitle').textContent = {dashboard:'Dashboard',keys:'API Keys',models:'AI Models',users:'User Models',settings:'Settings',logs:'Logs'}[page];
            if (window.innerWidth < 768) toggleSidebar();
            if (page === 'dashboard') loadDashboard();
            else if (page === 'keys') loadKeys();
            else if (page === 'models') loadModels();
            else if (page === 'users') loadUsers();
            else if (page === 'settings') loadSettings();
            else if (page === 'logs') loadLogs();
        }

        // Dashboard
        async function loadDashboard() {
            const r = await fetch('/api/stats', {credentials:'include'});
            const d = await r.json();
            document.getElementById('stat-keys').textContent = d.active_keys + '/' + d.total_keys;
            document.getElementById('stat-models').textContent = d.enabled_models + '/' + d.total_models;
            document.getElementById('stat-default').textContent = d.default_model;
            document.getElementById('stat-users').textContent = d.user_models_count;
        }

        // API Keys
        async function loadKeys() {
            const r = await fetch('/api/keys', {credentials:'include'});
            keys = await r.json();
            const c = document.getElementById('keysList');
            if (!keys.length) { c.innerHTML = '<p class="text-gray-400">No API keys. Click + Add to create one.</p>'; return; }
            c.innerHTML = keys.map(k => `
                <div class="glass rounded-xl p-4 border border-gray-700 flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-2">
                            <span class="font-medium">${k.name}</span>
                            <span class="text-xs px-2 py-0.5 rounded ${k.is_active ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">${k.is_active ? 'Active' : 'Inactive'}</span>
                        </div>
                        <p class="text-sm text-gray-400">${k.key_masked || '****'}</p>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="testKey('${k.name}')" class="px-3 py-1 bg-blue-600 rounded hover:bg-blue-700 text-sm">Test</button>
                        <button onclick="toggleKey(${k.id}, ${!k.is_active})" class="px-3 py-1 ${k.is_active ? 'bg-orange-600' : 'bg-green-600'} rounded hover:opacity-80 text-sm">${k.is_active ? 'Disable' : 'Enable'}</button>
                        <button onclick="deleteKey(${k.id})" class="px-3 py-1 bg-red-600 rounded hover:bg-red-700 text-sm">✕</button>
                    </div>
                </div>
            `).join('');
        }

        async function testKey(name) {
            alert('Testing ' + name + '...');
            const r = await fetch('/api/keys/test/' + name, {method:'POST', credentials:'include'});
            const d = await r.json();
            alert(name + ': ' + (d.success ? '✅ Working! (' + d.time + 'ms)' : '❌ ' + d.message));
            loadKeys();
        }

        async function toggleKey(id, active) {
            await fetch('/api/keys/' + id, {method:'PUT', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({is_active:active})});
            loadKeys();
        }

        async function deleteKey(id) {
            if (!confirm('Delete this API key?')) return;
            await fetch('/api/keys/' + id, {method:'DELETE', credentials:'include'});
            loadKeys();
        }

        function showAddKeyModal() {
            showModal(`
                <div class="p-4">
                    <h3 class="text-lg font-bold mb-4">Add API Key</h3>
                    <input type="text" id="newKeyName" placeholder="Name (e.g., groq)" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-3 outline-none">
                    <select id="newKeyProvider" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-3 outline-none">
                        <option value="groq">Groq</option>
                        <option value="openrouter">OpenRouter</option>
                        <option value="gemini">Gemini</option>
                        <option value="cerebras">Cerebras</option>
                        <option value="mistral">Mistral</option>
                        <option value="together">Together</option>
                        <option value="cohere">Cohere</option>
                        <option value="sambanova">SambaNova</option>
                        <option value="tavily">Tavily</option>
                        <option value="custom">Custom</option>
                    </select>
                    <input type="password" id="newKeyValue" placeholder="API Key" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-4 outline-none">
                    <div class="flex gap-2">
                        <button onclick="closeModal()" class="flex-1 py-2 bg-gray-700 rounded-lg">Cancel</button>
                        <button onclick="addKey()" class="flex-1 py-2 bg-indigo-600 rounded-lg">Add</button>
                    </div>
                </div>
            `);
        }

        async function addKey() {
            const r = await fetch('/api/keys', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: document.getElementById('newKeyName').value,
                    provider: document.getElementById('newKeyProvider').value,
                    key_value: document.getElementById('newKeyValue').value
                })
            });
            closeModal();
            if (r.ok) loadKeys();
            else alert('Failed to add key');
        }

        // Models
        async function loadModels() {
            const r = await fetch('/api/models', {credentials:'include'});
            models = await r.json();
            renderModels();
        }

        function filterModels(f) {
            currentFilter = f;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('bg-indigo-600'));
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.add('bg-gray-700'));
            document.querySelector('[data-filter="' + f + '"]')?.classList.remove('bg-gray-700');
            document.querySelector('[data-filter="' + f + '"]')?.classList.add('bg-indigo-600');
            renderModels();
        }

        function renderModels() {
            const filtered = currentFilter === 'all' ? models : models.filter(m => m.category === currentFilter);
            const c = document.getElementById('modelsList');
            if (!filtered.length) { c.innerHTML = '<p class="text-gray-400">No models found.</p>'; return; }
            c.innerHTML = filtered.map(m => `
                <div class="glass rounded-xl p-3 border border-gray-700 flex items-center justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="text-xl">${m.emoji}</span>
                        <div class="min-w-0">
                            <div class="flex items-center gap-2">
                                <span class="font-medium truncate">${m.name}</span>
                                ${m.is_default ? '<span class="text-xs px-1 bg-yellow-500/20 text-yellow-400 rounded">Default</span>' : ''}
                            </div>
                            <p class="text-xs text-gray-400 truncate">${m.provider} / ${m.model_id}</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-1 shrink-0">
                        <button onclick="setDefault('${m.id}')" class="px-2 py-1 bg-yellow-600 rounded text-xs hover:bg-yellow-700" title="Set Default">⭐</button>
                        <button onclick="toggleModelEnabled('${m.id}', ${!m.is_enabled})" class="px-2 py-1 ${m.is_enabled ? 'bg-green-600' : 'bg-gray-600'} rounded text-xs">${m.is_enabled ? 'On' : 'Off'}</button>
                        <button onclick="deleteModel('${m.id}')" class="px-2 py-1 bg-red-600 rounded text-xs hover:bg-red-700">✕</button>
                    </div>
                </div>
            `).join('');
        }

        async function setDefault(id) {
            await fetch('/api/models/' + id + '/set-default', {method:'POST', credentials:'include'});
            loadModels();
            loadDashboard();
            alert('Default model set to: ' + id);
        }

        async function toggleModelEnabled(id, enabled) {
            await fetch('/api/models/' + id + '/toggle', {method:'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled})});
            loadModels();
        }

        async function deleteModel(id) {
            if (!confirm('Delete model ' + id + '?')) return;
            await fetch('/api/models/' + id, {method:'DELETE', credentials:'include'});
            loadModels();
        }

        async function resetModels() {
            if (!confirm('Reset all models to defaults?')) return;
            await fetch('/api/models/reset', {method:'POST', credentials:'include'});
            loadModels();
            alert('Models reset to defaults!');
        }

        function showAddModelModal() {
            showModal(`
                <div class="p-4">
                    <h3 class="text-lg font-bold mb-4">Add Model</h3>
                    <input type="text" id="newModelId" placeholder="ID (e.g., my_model)" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-2 outline-none">
                    <input type="text" id="newModelEmoji" placeholder="Emoji (e.g., 🤖)" maxlength="2" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-2 outline-none">
                    <input type="text" id="newModelName" placeholder="Display Name" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-2 outline-none">
                    <input type="text" id="newModelProvider" placeholder="Provider (e.g., groq)" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-2 outline-none">
                    <input type="text" id="newModelApiId" placeholder="API Model ID" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-4 outline-none">
                    <div class="flex gap-2">
                        <button onclick="closeModal()" class="flex-1 py-2 bg-gray-700 rounded-lg">Cancel</button>
                        <button onclick="addModel()" class="flex-1 py-2 bg-indigo-600 rounded-lg">Add</button>
                    </div>
                </div>
            `);
        }

        async function addModel() {
            const r = await fetch('/api/models', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id: document.getElementById('newModelId').value,
                    emoji: document.getElementById('newModelEmoji').value || '🤖',
                    name: document.getElementById('newModelName').value,
                    provider: document.getElementById('newModelProvider').value,
                    model_id: document.getElementById('newModelApiId').value,
                    category: 'custom'
                })
            });
            closeModal();
            if (r.ok) loadModels();
            else alert('Failed to add model');
        }

        // User Models
        async function loadUsers() {
            const r = await fetch('/api/user-models', {credentials:'include'});
            userModels = await r.json();
            const entries = Object.entries(userModels);
            const c = document.getElementById('usersList');
            if (!entries.length) { c.innerHTML = '<p class="text-gray-400">No user-specific models. Click + Add to assign.</p>'; return; }
            c.innerHTML = entries.map(([uid, mid]) => `
                <div class="glass rounded-xl p-3 border border-gray-700 flex items-center justify-between">
                    <div>
                        <p class="font-mono">${uid}</p>
                        <p class="text-sm text-gray-400">${mid}</p>
                    </div>
                    <button onclick="deleteUserModel('${uid}')" class="px-3 py-1 bg-red-600 rounded hover:bg-red-700 text-sm">✕</button>
                </div>
            `).join('');
        }

        async function deleteUserModel(uid) {
            if (!confirm('Remove model for user ' + uid + '?')) return;
            await fetch('/api/user-models/' + uid, {method:'DELETE', credentials:'include'});
            loadUsers();
        }

        function showAddUserModal() {
            const opts = models.filter(m => m.is_enabled).map(m => `<option value="${m.id}">${m.emoji} ${m.name}</option>`).join('');
            showModal(`
                <div class="p-4">
                    <h3 class="text-lg font-bold mb-4">Add User Model</h3>
                    <input type="text" id="newUserId" placeholder="Discord User ID" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-3 outline-none">
                    <select id="newUserModelId" class="w-full px-3 py-2 bg-[#0f0f1a] border border-gray-600 rounded-lg mb-4 outline-none">${opts}</select>
                    <div class="flex gap-2">
                        <button onclick="closeModal()" class="flex-1 py-2 bg-gray-700 rounded-lg">Cancel</button>
                        <button onclick="addUserModel()" class="flex-1 py-2 bg-indigo-600 rounded-lg">Add</button>
                    </div>
                </div>
            `);
        }

        async function addUserModel() {
            const r = await fetch('/api/user-models/' + document.getElementById('newUserId').value, {
                method: 'PUT', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({model_id: document.getElementById('newUserModelId').value})
            });
            closeModal();
            if (r.ok) loadUsers();
        }

        // Settings
        async function loadSettings() {
            const r = await fetch('/api/settings', {credentials:'include'});
            const d = await r.json();
            document.getElementById('set-system_prompt').value = d.system_prompt || '';
            document.getElementById('set-max_memory_messages').value = d.max_memory_messages || '25';
            document.getElementById('set-memory_timeout_minutes').value = d.memory_timeout_minutes || '30';
        }

        async function saveSettings() {
            await fetch('/api/settings', {
                method: 'PUT', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    system_prompt: document.getElementById('set-system_prompt').value,
                    max_memory_messages: document.getElementById('set-max_memory_messages').value,
                    memory_timeout_minutes: document.getElementById('set-memory_timeout_minutes').value
                })
            });
            alert('Settings saved!');
        }

        // Logs
        async function loadLogs() {
            const r = await fetch('/api/logs/activity', {credentials:'include'});
            const logs = await r.json();
            const c = document.getElementById('logsList');
            if (!logs.length) { c.innerHTML = '<p class="text-gray-400">No logs yet.</p>'; return; }
            c.innerHTML = logs.map(l => `
                <div class="glass rounded-lg p-3 border border-gray-700">
                    <div class="flex justify-between">
                        <span class="font-medium">${l.action}</span>
                        <span class="text-xs text-gray-400">${l.time}</span>
                    </div>
                    ${l.details ? '<p class="text-sm text-gray-400">' + l.details + '</p>' : ''}
                </div>
            `).join('');
        }

        // Modal
        function showModal(html) {
            document.getElementById('modalContent').innerHTML = html;
            document.getElementById('modal').classList.remove('hidden');
            document.getElementById('modal').classList.add('flex');
        }

        function closeModal() {
            document.getElementById('modal').classList.add('hidden');
            document.getElementById('modal').classList.remove('flex');
        }

        document.getElementById('modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };

        // Init
        checkAuth();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

print("✅ All routes registered", flush=True)

if __name__ == '__main__':
    print(f"🌐 Starting on port {PORT}", flush=True)
    app.run(host='0.0.0.0', port=PORT)