import os
import json
import time
import hashlib
import requests
from functools import wraps
from flask import Flask, request, jsonify, render_template, make_response
from flask_cors import CORS
from database import Database

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configuration
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
BOT_SECRET = os.getenv("BOT_SECRET", "bot_secret_key")
PORT = int(os.getenv("PORT", 8080))

db = Database()

# ==================== Helpers ====================

def verify_password(password):
    stored_hash = db.get_setting('admin_password_hash')
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
    
    db.add_activity_log('Login Failed', 'Invalid password attempt', request.remote_addr)
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
    db.add_activity_log('Password Changed', None, request.remote_addr)
    return jsonify({'success': True})

# ==================== Bot Integration API ====================

@app.route('/api/bot/config', methods=['GET'])
@require_bot_secret
def get_bot_config():
    api_keys = db.get_all_api_keys()
    keys_dict = {k['name']: k['key_value'] for k in api_keys if k['is_active']}
    
    return jsonify({
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
    })

# ==================== API Keys Routes ====================

@app.route('/api/keys', methods=['GET'])
@require_auth
def get_keys():
    keys = db.get_all_api_keys()
    for k in keys:
        if k['key_value']:
            k['key_masked'] = k['key_value'][:8] + '...' + k['key_value'][-4:] if len(k['key_value']) > 12 else '****'
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
        db.add_activity_log('API Key Added', f'Added key: {name}', request.remote_addr)
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/keys/<int:key_id>', methods=['PUT'])
@require_auth
def update_key(key_id):
    data = request.get_json() or {}
    db.update_api_key(key_id, 
                      key_value=data.get('key_value'),
                      is_active=data.get('is_active'))
    db.add_activity_log('API Key Updated', f'Updated key ID: {key_id}', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/keys/<int:key_id>', methods=['DELETE'])
@require_auth
def delete_key(key_id):
    db.delete_api_key(key_id)
    db.add_activity_log('API Key Deleted', f'Deleted key ID: {key_id}', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/keys/test/<string:name>', methods=['POST'])
@require_auth
def test_key(name):
    key = db.get_api_key(name)
    if not key:
        return jsonify({'error': 'Key not found or inactive'}), 404
    
    start_time = time.time()
    result = {'success': False, 'message': '', 'time': 0}
    
    try:
        if name == 'groq':
            r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'cerebras':
            r = requests.post('https://api.cerebras.ai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'llama-3.3-70b', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'openrouter':
            r = requests.post('https://openrouter.ai/api/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'meta-llama/llama-3.3-70b-instruct:free', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'gemini':
            r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={key}',
                            headers={'Content-Type': 'application/json'},
                            json={'contents': [{'parts': [{'text': 'Hi'}]}]},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'mistral':
            r = requests.post('https://api.mistral.ai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'mistral-small-latest', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'together':
            r = requests.post('https://api.together.xyz/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'cohere':
            r = requests.post('https://api.cohere.com/v1/chat',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'command-r-plus-08-2024', 'message': 'Hi'},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'sambanova':
            r = requests.post('https://api.sambanova.ai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'Meta-Llama-3.3-70B-Instruct', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        elif name == 'tavily':
            r = requests.post('https://api.tavily.com/search',
                            json={'api_key': key, 'query': 'test', 'max_results': 1},
                            timeout=15)
            result['success'] = r.status_code == 200
            
        else:
            result['message'] = 'Unknown provider - manual test required'
            result['success'] = None
        
        result['time'] = round((time.time() - start_time) * 1000)
        result['message'] = 'Working!' if result['success'] else 'Failed'
        
    except requests.exceptions.Timeout:
        result['message'] = 'Request timeout'
        result['time'] = round((time.time() - start_time) * 1000)
    except Exception as e:
        result['message'] = str(e)[:100]
        result['time'] = round((time.time() - start_time) * 1000)
    
    status = 'success' if result['success'] else 'failed' if result['success'] is False else 'unknown'
    db.update_api_test_result(name, status, result['time'], result['message'] if not result['success'] else None)
    db.add_activity_log('API Test', f'{name}: {status}', request.remote_addr)
    
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
    required = ['id', 'name', 'provider', 'model_id']
    
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    
    success, message = db.add_model(
        data['id'], data.get('emoji', '🤖'), data['name'],
        data.get('description', ''), data.get('category', 'custom'),
        data['provider'], data['model_id']
    )
    
    if success:
        db.add_activity_log('Model Added', f'Added: {data["id"]}', request.remote_addr)
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/models/<string:model_id>', methods=['PUT'])
@require_auth
def update_model(model_id):
    data = request.get_json() or {}
    db.update_model(model_id, **data)
    db.add_activity_log('Model Updated', f'Updated: {model_id}', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/models/<string:model_id>', methods=['DELETE'])
@require_auth
def delete_model(model_id):
    db.delete_model(model_id)
    db.add_activity_log('Model Deleted', f'Deleted: {model_id}', request.remote_addr)
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
    db.add_activity_log('Default Model Changed', f'Set default: {model_id}', request.remote_addr)
    return jsonify({'success': True})

# ==================== User Models Routes ====================

@app.route('/api/user-models', methods=['GET'])
@require_auth
def get_user_models():
    return jsonify(db.get_all_user_models())

@app.route('/api/user-models/<string:user_id>', methods=['PUT'])
@require_auth
def set_user_model(user_id):
    data = request.get_json() or {}
    model_id = data.get('model_id')
    if model_id:
        db.set_user_model(user_id, model_id)
        return jsonify({'success': True})
    return jsonify({'error': 'model_id required'}), 400

@app.route('/api/user-models/<string:user_id>', methods=['DELETE'])
@require_auth
def delete_user_model(user_id):
    db.delete_user_model(user_id)
    return jsonify({'success': True})

# ==================== Settings Routes ====================

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
    db.add_activity_log('Settings Updated', None, request.remote_addr)
    return jsonify({'success': True})

# ==================== Logs Routes ====================

@app.route('/api/logs/activity', methods=['GET'])
@require_auth
def get_activity_logs():
    limit = request.args.get('limit', 50, type=int)
    return jsonify(db.get_activity_logs(limit))

@app.route('/api/logs/tests', methods=['GET'])
@require_auth
def get_test_logs():
    limit = request.args.get('limit', 50, type=int)
    return jsonify(db.get_test_logs(limit))

# ==================== Dashboard Stats ====================

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    api_keys = db.get_all_api_keys()
    models = db.get_all_models()
    
    return jsonify({
        'total_keys': len(api_keys),
        'active_keys': len([k for k in api_keys if k['is_active']]),
        'total_models': len(models),
        'enabled_models': len([m for m in models if m['is_enabled']]),
        'default_model': db.get_setting('default_model', 'groq'),
        'user_models_count': len(db.get_all_user_models())
    })

# ==================== Health Check ====================

@app.route('/api/keepalive', methods=['GET'])
def keepalive():
    return jsonify({'status': 'ok', 'time': time.time()})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

# ==================== Frontend ====================

@app.route('/')
def index():
    return render_template('index.html')

# ==================== Run ====================

if __name__ == '__main__':
    print("=" * 50)
    print(f"🌐 Web Panel Starting on port {PORT}")
    print(f"🔑 Admin Key: {ADMIN_KEY}")
    print(f"🤖 Bot Secret: {BOT_SECRET[:10]}...")
    print("=" * 50)
    app.run(host='0.0.0.0', port=PORT, debug=False)