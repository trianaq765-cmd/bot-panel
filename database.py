import sqlite3
import json
import threading
import time
import hashlib
import secrets
from datetime import datetime

class Database:
    def __init__(self, path="panel.db"):
        self.path = path
        self.lock = threading.Lock()
        self._init_db()
    
    def _get_conn(self):
        return sqlite3.connect(self.path, check_same_thread=False)
    
    def _init_db(self):
        with self.lock:
            conn = self._get_conn()
            conn.executescript('''
                -- API Keys table
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    key_value TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    last_tested TEXT,
                    test_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- AI Models table
                CREATE TABLE IF NOT EXISTS ai_models (
                    id TEXT PRIMARY KEY,
                    emoji TEXT DEFAULT '🤖',
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT DEFAULT 'main',
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    is_enabled INTEGER DEFAULT 1,
                    is_default INTEGER DEFAULT 0,
                    priority INTEGER DEFAULT 100,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- User model preferences
                CREATE TABLE IF NOT EXISTS user_models (
                    user_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Settings table
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Admin sessions
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL
                );
                
                -- API test logs
                CREATE TABLE IF NOT EXISTS test_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_time REAL,
                    error_message TEXT,
                    tested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Activity logs
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            conn.commit()
            conn.close()
            self._seed_default_models()
    
    def _seed_default_models(self):
        """Seed default AI models if empty"""
        with self.lock:
            conn = self._get_conn()
            count = conn.execute('SELECT COUNT(*) FROM ai_models').fetchone()[0]
            if count == 0:
                default_models = [
                    # Main providers
                    ('groq', '⚡', 'Groq', 'Llama 3.3 70B Versatile', 'main', 'groq', 'llama-3.3-70b-versatile', 1, 1, 10),
                    ('groq_8b', '⚡', 'Groq-8B', 'Llama 3.1 8B Instant', 'main', 'groq', 'llama-3.1-8b-instant', 1, 0, 11),
                    ('groq_maverick', '🦙', 'Groq-Maverick', 'Llama 4 Maverick', 'main', 'groq', 'meta-llama/llama-4-maverick-17b-128e-instruct', 1, 0, 12),
                    ('groq_scout', '🔍', 'Groq-Scout', 'Llama 4 Scout', 'main', 'groq', 'meta-llama/llama-4-scout-17b-16e-instruct', 1, 0, 13),
                    ('groq_kimi', '🌙', 'Groq-Kimi', 'Kimi K2 Instruct', 'main', 'groq', 'moonshotai/kimi-k2-instruct', 1, 0, 14),
                    ('cerebras', '🧠', 'Cerebras', 'Llama 3.3 70B', 'main', 'cerebras', 'llama-3.3-70b', 1, 0, 20),
                    ('sambanova', '🦣', 'SambaNova', 'Llama 3.3 70B Instruct', 'main', 'sambanova', 'Meta-Llama-3.3-70B-Instruct', 1, 0, 30),
                    ('cloudflare', '☁️', 'Cloudflare', 'Llama 3.3 70B', 'main', 'cloudflare', '@cf/meta/llama-3.3-70b-instruct-fp8-fast', 1, 0, 40),
                    ('cohere', '🔷', 'Cohere', 'Command R+', 'main', 'cohere', 'command-r-plus-08-2024', 1, 0, 50),
                    ('mistral', 'Ⓜ️', 'Mistral', 'Mistral Small', 'main', 'mistral', 'mistral-small-latest', 1, 0, 60),
                    ('together', '🤝', 'Together', 'Llama 3.3 Turbo', 'main', 'together', 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 1, 0, 70),
                    ('moonshot', '🌙', 'Moonshot', 'Kimi 128K', 'main', 'moonshot', 'moonshot-v1-8k', 1, 0, 80),
                    ('huggingface', '🤗', 'HuggingFace', 'Mixtral 8x7B', 'main', 'huggingface', 'mistralai/Mixtral-8x7B-Instruct-v0.1', 1, 0, 90),
                    ('replicate', '🔄', 'Replicate', 'Llama 405B', 'main', 'replicate', 'meta/meta-llama-3.1-405b-instruct', 1, 0, 100),
                    ('tavily', '🔍', 'Tavily', 'Web Search', 'main', 'tavily', 'search', 1, 0, 110),
                    
                    # Gemini
                    ('gemini_flash', '💎', 'Gemini Flash', '2.0 Flash Lite', 'gemini', 'gemini', 'gemini-2.0-flash-lite', 1, 0, 200),
                    ('gemini_lite', '💎', 'Gemini Lite', 'Flash Lite Latest', 'gemini', 'gemini', 'gemini-flash-lite-latest', 1, 0, 201),
                    ('gemini_pro', '💎', 'Gemini Pro', '1.5 Pro', 'gemini', 'gemini', 'gemini-1.5-pro', 1, 0, 202),
                    
                    # OpenRouter
                    ('or_llama', '🦙', 'OR-Llama', 'Llama 3.3 70B Free', 'openrouter', 'openrouter', 'meta-llama/llama-3.3-70b-instruct:free', 1, 0, 300),
                    ('or_gemini', '💎', 'OR-Gemini', 'Gemini 2.0 Free', 'openrouter', 'openrouter', 'google/gemini-2.0-flash-exp:free', 1, 0, 301),
                    ('or_molmo', '👁️', 'OR-Molmo', 'Molmo2 8B', 'openrouter', 'openrouter', 'allenai/molmo-2-8b:free', 1, 0, 302),
                    ('or_mimo', '🎭', 'OR-MiMo', 'MiMo V2 Flash', 'openrouter', 'openrouter', 'xiaomi/mimo-v2-flash:free', 1, 0, 303),
                    ('or_nemotron', '🔥', 'OR-Nemotron', 'Nemotron 3 Nano', 'openrouter', 'openrouter', 'nvidia/nemotron-3-nano-30b-a3b:free', 1, 0, 304),
                    ('or_devstral', '💻', 'OR-Devstral', 'Devstral 2', 'openrouter', 'openrouter', 'mistralai/devstral-2-2512:free', 1, 0, 305),
                    ('or_trinity', '🔺', 'OR-Trinity', 'Trinity Mini', 'openrouter', 'openrouter', 'trinity/trinity-mini:free', 1, 0, 306),
                    ('or_glm', '🇨🇳', 'OR-GLM', 'GLM 4.5 Air', 'openrouter', 'openrouter', 'zhipu/glm-4.5-air:free', 1, 0, 307),
                    ('or_kimi', '🌙', 'OR-Kimi', 'Kimi K2', 'openrouter', 'openrouter', 'moonshot/kimi-k2-0711:free', 1, 0, 308),
                    ('or_uncensored', '🔓', 'OR-Uncensored', 'Uncensored Model', 'openrouter', 'openrouter', 'undi95/uncensored:free', 1, 0, 309),
                    ('or_r1', '🧠', 'OR-DeepSeek R1', 'R1 0528', 'openrouter', 'openrouter', 'deepseek/deepseek-r1-0528:free', 1, 0, 310),
                    ('or_r1t', '🧠', 'OR-R1T Chimera', 'R1T Chimera', 'openrouter', 'openrouter', 'deepseek/r1t-chimera:free', 1, 0, 311),
                    ('or_qwen', '🔮', 'OR-Qwen', 'Qwen3 235B', 'openrouter', 'openrouter', 'qwen/qwen3-235b-a22b:free', 1, 0, 312),
                    
                    # Pollinations Free
                    ('pf_openai', '🆓', 'PollFree-OpenAI', 'GPT-5 Mini', 'pollinations', 'pollinations_free', 'openai', 1, 0, 400),
                    ('pf_fast', '⚡', 'PollFree-Fast', 'GPT-5 Nano', 'pollinations', 'pollinations_free', 'openai-fast', 1, 0, 401),
                    ('pf_nova', '🚀', 'PollFree-Nova', 'Amazon Nova', 'pollinations', 'pollinations_free', 'nova-fast', 1, 0, 402),
                    ('pf_mistral', 'Ⓜ️', 'PollFree-Mistral', 'Mistral 3.2', 'pollinations', 'pollinations_free', 'mistral', 1, 0, 403),
                    ('pf_gemini', '💎', 'PollFree-Gemini', 'Gemini 2.5 Lite', 'pollinations', 'pollinations_free', 'gemini-fast', 1, 0, 404),
                    ('pf_qwen', '🔮', 'PollFree-Qwen', 'Qwen3 Coder', 'pollinations', 'pollinations_free', 'qwen-coder', 1, 0, 405),
                    ('pf_deepseek', '🌊', 'PollFree-DeepSeek', 'DeepSeek V3.2', 'pollinations', 'pollinations_free', 'deepseek', 1, 0, 406),
                    ('pf_grok', '❌', 'PollFree-Grok', 'Grok 4 Fast', 'pollinations', 'pollinations_free', 'grok', 1, 0, 407),
                    ('pf_sonar', '🔍', 'PollFree-Sonar', 'Perplexity Sonar', 'pollinations', 'pollinations_free', 'sonar', 1, 0, 408),
                    ('poll_free', '🌸', 'PollFree-Auto', 'Auto Select', 'pollinations', 'pollinations_free', 'auto', 1, 0, 409),
                    
                    # Pollinations API (paid)
                    ('pa_openai', '🔑', 'PollAPI-OpenAI', 'OpenAI with Key', 'pollinations_api', 'pollinations_api', 'openai', 1, 0, 500),
                    ('pa_claude', '🔑', 'PollAPI-Claude', 'Claude with Key', 'pollinations_api', 'pollinations_api', 'claude', 1, 0, 501),
                ]
                
                conn.executemany('''
                    INSERT OR IGNORE INTO ai_models 
                    (id, emoji, name, description, category, provider, model_id, is_enabled, is_default, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', default_models)
                
                # Default settings
                default_settings = [
                    ('default_model', 'groq'),
                    ('system_prompt', 'You are a helpful AI assistant. Default language: Bahasa Indonesia.'),
                    ('max_memory_messages', '25'),
                    ('memory_timeout_minutes', '30'),
                    ('rate_limit_ai', '5'),
                    ('rate_limit_img', '15'),
                    ('rate_limit_dump', '10'),
                    ('admin_password_hash', hashlib.sha256('admin123'.encode()).hexdigest()),
                ]
                
                conn.executemany('''
                    INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)
                ''', default_settings)
                
                conn.commit()
            conn.close()
    
    # ==================== API Keys ====================
    
    def get_all_api_keys(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('''
                SELECT id, name, key_value, provider, is_active, last_tested, test_status, created_at
                FROM api_keys ORDER BY provider, name
            ''').fetchall()
            conn.close()
            return [{
                'id': r[0], 'name': r[1], 'key_value': r[2], 'provider': r[3],
                'is_active': bool(r[4]), 'last_tested': r[5], 'test_status': r[6], 'created_at': r[7]
            } for r in rows]
    
    def get_api_key(self, name):
        with self.lock:
            conn = self._get_conn()
            row = conn.execute('SELECT key_value FROM api_keys WHERE name = ? AND is_active = 1', (name,)).fetchone()
            conn.close()
            return row[0] if row else None
    
    def add_api_key(self, name, key_value, provider):
        with self.lock:
            conn = self._get_conn()
            try:
                conn.execute('''
                    INSERT INTO api_keys (name, key_value, provider) VALUES (?, ?, ?)
                ''', (name, key_value, provider))
                conn.commit()
                return True, "API key added successfully"
            except sqlite3.IntegrityError:
                return False, "API key with this name already exists"
            finally:
                conn.close()
    
    def update_api_key(self, key_id, key_value=None, is_active=None):
        with self.lock:
            conn = self._get_conn()
            updates = []
            params = []
            if key_value is not None:
                updates.append("key_value = ?")
                params.append(key_value)
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(key_id)
                conn.execute(f"UPDATE api_keys SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
            conn.close()
            return True
    
    def delete_api_key(self, key_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
            conn.commit()
            conn.close()
            return True
    
    def update_api_test_result(self, name, status, response_time=None, error=None):
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                UPDATE api_keys SET last_tested = CURRENT_TIMESTAMP, test_status = ? WHERE name = ?
            ''', (status, name))
            conn.execute('''
                INSERT INTO test_logs (api_name, status, response_time, error_message) VALUES (?, ?, ?, ?)
            ''', (name, status, response_time, error))
            conn.commit()
            conn.close()
    
    # ==================== AI Models ====================
    
    def get_all_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('''
                SELECT id, emoji, name, description, category, provider, model_id, is_enabled, is_default, priority
                FROM ai_models ORDER BY priority, name
            ''').fetchall()
            conn.close()
            return [{
                'id': r[0], 'emoji': r[1], 'name': r[2], 'description': r[3],
                'category': r[4], 'provider': r[5], 'model_id': r[6],
                'is_enabled': bool(r[7]), 'is_default': bool(r[8]), 'priority': r[9]
            } for r in rows]
    
    def get_enabled_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('''
                SELECT id, emoji, name, description, category, provider, model_id
                FROM ai_models WHERE is_enabled = 1 ORDER BY priority, name
            ''').fetchall()
            conn.close()
            return {r[0]: {
                'e': r[1], 'n': r[2], 'd': r[3], 'c': r[4], 'p': r[5], 'm': r[6]
            } for r in rows}
    
    def get_model(self, model_id):
        with self.lock:
            conn = self._get_conn()
            row = conn.execute('SELECT * FROM ai_models WHERE id = ?', (model_id,)).fetchone()
            conn.close()
            return row
    
    def add_model(self, id, emoji, name, description, category, provider, model_id):
        with self.lock:
            conn = self._get_conn()
            try:
                conn.execute('''
                    INSERT INTO ai_models (id, emoji, name, description, category, provider, model_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (id, emoji, name, description, category, provider, model_id))
                conn.commit()
                return True, "Model added successfully"
            except sqlite3.IntegrityError:
                return False, "Model with this ID already exists"
            finally:
                conn.close()
    
    def update_model(self, model_id, **kwargs):
        with self.lock:
            conn = self._get_conn()
            valid_fields = ['emoji', 'name', 'description', 'category', 'provider', 'model_id', 'is_enabled', 'is_default', 'priority']
            updates = []
            params = []
            for key, value in kwargs.items():
                if key in valid_fields:
                    updates.append(f"{key} = ?")
                    params.append(value)
            if updates:
                params.append(model_id)
                conn.execute(f"UPDATE ai_models SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
            conn.close()
            return True
    
    def delete_model(self, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM ai_models WHERE id = ?', (model_id,))
            conn.commit()
            conn.close()
            return True
    
    def set_default_model(self, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('UPDATE ai_models SET is_default = 0')
            conn.execute('UPDATE ai_models SET is_default = 1 WHERE id = ?', (model_id,))
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_model', ?)", (model_id,))
            conn.commit()
            conn.close()
            return True
    
    # ==================== User Models ====================
    
    def get_user_model(self, user_id):
        with self.lock:
            conn = self._get_conn()
            row = conn.execute('SELECT model_id FROM user_models WHERE user_id = ?', (str(user_id),)).fetchone()
            conn.close()
            return row[0] if row else None
    
    def set_user_model(self, user_id, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                INSERT OR REPLACE INTO user_models (user_id, model_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (str(user_id), model_id))
            conn.commit()
            conn.close()
            return True
    
    def get_all_user_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT user_id, model_id, updated_at FROM user_models').fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
    
    def delete_user_model(self, user_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM user_models WHERE user_id = ?', (str(user_id),))
            conn.commit()
            conn.close()
            return True
    
    # ==================== Settings ====================
    
    def get_setting(self, key, default=None):
        with self.lock:
            conn = self._get_conn()
            row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
            conn.close()
            return row[0] if row else default
    
    def set_setting(self, key, value):
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, str(value)))
            conn.commit()
            conn.close()
            return True
    
    def get_all_settings(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT key, value FROM settings').fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
    
    # ==================== Sessions ====================
    
    def create_session(self):
        token = secrets.token_urlsafe(32)
        expires = datetime.now().timestamp() + 86400  # 24 hours
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM sessions WHERE expires_at < ?', (datetime.now().isoformat(),))
            conn.execute('INSERT INTO sessions (token, expires_at) VALUES (?, ?)', 
                        (token, datetime.fromtimestamp(expires).isoformat()))
            conn.commit()
            conn.close()
        return token
    
    def validate_session(self, token):
        if not token:
            return False
        with self.lock:
            conn = self._get_conn()
            row = conn.execute('''
                SELECT 1 FROM sessions WHERE token = ? AND expires_at > ?
            ''', (token, datetime.now().isoformat())).fetchone()
            conn.close()
            return row is not None
    
    def delete_session(self, token):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            conn.close()
    
    # ==================== Logs ====================
    
    def add_activity_log(self, action, details=None, ip=None):
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                INSERT INTO activity_logs (action, details, ip_address) VALUES (?, ?, ?)
            ''', (action, details, ip))
            conn.commit()
            conn.close()
    
    def get_activity_logs(self, limit=50):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('''
                SELECT action, details, ip_address, created_at 
                FROM activity_logs ORDER BY id DESC LIMIT ?
            ''', (limit,)).fetchall()
            conn.close()
            return [{'action': r[0], 'details': r[1], 'ip': r[2], 'time': r[3]} for r in rows]
    
    def get_test_logs(self, limit=50):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('''
                SELECT api_name, status, response_time, error_message, tested_at
                FROM test_logs ORDER BY id DESC LIMIT ?
            ''', (limit,)).fetchall()
            conn.close()
            return [{'api': r[0], 'status': r[1], 'time': r[2], 'error': r[3], 'tested_at': r[4]} for r in rows]
