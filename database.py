import sqlite3
import threading
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
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    key_value TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    last_tested TEXT,
                    test_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
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
                    priority INTEGER DEFAULT 100
                );
                
                CREATE TABLE IF NOT EXISTS user_models (
                    user_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    details TEXT,
                    ip_address TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS test_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_name TEXT,
                    status TEXT,
                    response_time REAL,
                    error_message TEXT,
                    tested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            conn.commit()
            
            # Set default password
            r = conn.execute("SELECT 1 FROM settings WHERE key='admin_password_hash'").fetchone()
            if not r:
                h = hashlib.sha256('admin123'.encode()).hexdigest()
                conn.execute("INSERT INTO settings VALUES('admin_password_hash', ?)", (h,))
                conn.execute("INSERT OR IGNORE INTO settings VALUES('default_model', 'groq')")
                conn.execute("INSERT OR IGNORE INTO settings VALUES('system_prompt', 'You are a helpful AI assistant.')")
                conn.commit()
            
            conn.close()
    
    # ===== Settings =====
    def get_setting(self, key, default=None):
        with self.lock:
            conn = self._get_conn()
            r = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            conn.close()
            return r[0] if r else default
    
    def set_setting(self, key, value):
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, str(value)))
            conn.commit()
            conn.close()
    
    def get_all_settings(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT key, value FROM settings').fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
    
    # ===== Sessions =====
    def create_session(self):
        token = secrets.token_urlsafe(32)
        expires = datetime.now().timestamp() + 86400
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT INTO sessions VALUES(?,?)', (token, datetime.fromtimestamp(expires).isoformat()))
            conn.commit()
            conn.close()
        return token
    
    def validate_session(self, token):
        if not token:
            return False
        with self.lock:
            conn = self._get_conn()
            r = conn.execute('SELECT 1 FROM sessions WHERE token=? AND expires_at>?', 
                           (token, datetime.now().isoformat())).fetchone()
            conn.close()
            return r is not None
    
    def delete_session(self, token):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM sessions WHERE token=?', (token,))
            conn.commit()
            conn.close()
    
    # ===== API Keys =====
    def get_all_api_keys(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT id, name, key_value, provider, is_active, test_status FROM api_keys').fetchall()
            conn.close()
            return [{'id': r[0], 'name': r[1], 'key_value': r[2], 'provider': r[3], 'is_active': bool(r[4]), 'test_status': r[5]} for r in rows]
    
    def get_api_key(self, name):
        with self.lock:
            conn = self._get_conn()
            r = conn.execute('SELECT key_value FROM api_keys WHERE name=? AND is_active=1', (name,)).fetchone()
            conn.close()
            return r[0] if r else None
    
    def add_api_key(self, name, key_value, provider):
        with self.lock:
            conn = self._get_conn()
            try:
                conn.execute('INSERT INTO api_keys (name, key_value, provider) VALUES(?,?,?)', (name, key_value, provider))
                conn.commit()
                return True, "Added"
            except:
                return False, "Already exists"
            finally:
                conn.close()
    
    def update_api_key(self, key_id, key_value=None, is_active=None):
        with self.lock:
            conn = self._get_conn()
            if key_value is not None:
                conn.execute('UPDATE api_keys SET key_value=? WHERE id=?', (key_value, key_id))
            if is_active is not None:
                conn.execute('UPDATE api_keys SET is_active=? WHERE id=?', (1 if is_active else 0, key_id))
            conn.commit()
            conn.close()
    
    def delete_api_key(self, key_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM api_keys WHERE id=?', (key_id,))
            conn.commit()
            conn.close()
    
    def update_api_test_result(self, name, status, response_time=None, error=None):
        with self.lock:
            conn = self._get_conn()
            conn.execute('UPDATE api_keys SET test_status=? WHERE name=?', (status, name))
            conn.execute('INSERT INTO test_logs (api_name, status, response_time, error_message) VALUES(?,?,?,?)',
                        (name, status, response_time, error))
            conn.commit()
            conn.close()
    
    # ===== Models =====
    def get_all_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT id, emoji, name, description, category, provider, model_id, is_enabled, is_default, priority FROM ai_models ORDER BY priority').fetchall()
            conn.close()
            return [{'id': r[0], 'emoji': r[1], 'name': r[2], 'description': r[3], 'category': r[4], 'provider': r[5], 'model_id': r[6], 'is_enabled': bool(r[7]), 'is_default': bool(r[8]), 'priority': r[9]} for r in rows]
    
    def get_enabled_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT id, emoji, name, description, category, provider, model_id FROM ai_models WHERE is_enabled=1').fetchall()
            conn.close()
            return {r[0]: {'e': r[1], 'n': r[2], 'd': r[3], 'c': r[4], 'p': r[5], 'm': r[6]} for r in rows}
    
    def add_model(self, id, emoji, name, description, category, provider, model_id):
        with self.lock:
            conn = self._get_conn()
            try:
                conn.execute('INSERT INTO ai_models (id, emoji, name, description, category, provider, model_id) VALUES(?,?,?,?,?,?,?)',
                           (id, emoji, name, description, category, provider, model_id))
                conn.commit()
                return True, "Added"
            except:
                return False, "Already exists"
            finally:
                conn.close()
    
    def update_model(self, model_id, **kwargs):
        with self.lock:
            conn = self._get_conn()
            for k, v in kwargs.items():
                if k in ['emoji', 'name', 'description', 'category', 'provider', 'model_id', 'is_enabled', 'is_default', 'priority']:
                    conn.execute(f'UPDATE ai_models SET {k}=? WHERE id=?', (v, model_id))
            conn.commit()
            conn.close()
    
    def delete_model(self, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM ai_models WHERE id=?', (model_id,))
            conn.commit()
            conn.close()
    
    def set_default_model(self, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('UPDATE ai_models SET is_default=0')
            conn.execute('UPDATE ai_models SET is_default=1 WHERE id=?', (model_id,))
            conn.execute("INSERT OR REPLACE INTO settings VALUES('default_model', ?)", (model_id,))
            conn.commit()
            conn.close()
    
    # ===== User Models =====
    def get_all_user_models(self):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT user_id, model_id FROM user_models').fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
    
    def set_user_model(self, user_id, model_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT OR REPLACE INTO user_models VALUES(?,?)', (str(user_id), model_id))
            conn.commit()
            conn.close()
    
    def delete_user_model(self, user_id):
        with self.lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM user_models WHERE user_id=?', (str(user_id),))
            conn.commit()
            conn.close()
    
    # ===== Logs =====
    def add_activity_log(self, action, details=None, ip=None):
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT INTO activity_logs (action, details, ip_address) VALUES(?,?,?)', (action, details, ip))
            conn.commit()
            conn.close()
    
    def get_activity_logs(self, limit=50):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT action, details, ip_address, created_at FROM activity_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            conn.close()
            return [{'action': r[0], 'details': r[1], 'ip': r[2], 'time': r[3]} for r in rows]
    
    def get_test_logs(self, limit=50):
        with self.lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT api_name, status, response_time, error_message, tested_at FROM test_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            conn.close()
            return [{'api': r[0], 'status': r[1], 'time': r[2], 'error': r[3], 'tested_at': r[4]} for r in rows]