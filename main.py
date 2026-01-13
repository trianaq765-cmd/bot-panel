from fastapi import FastAPI,HTTPException,Depends,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.security import HTTPBasic,HTTPBasicCredentials
from contextlib import asynccontextmanager
import sqlite3,secrets,os,threading
ADMIN_USER=os.getenv("ADMIN_USER")or"admin"
ADMIN_PASS=os.getenv("ADMIN_PASS")or os.getenv("ADMIN_KEY")or"admin123"
BOT_SECRET=os.getenv("BOT_SECRET")or os.getenv("CONFIG_BOT_SECRET")or"bot_secret_123"
DB_PATH=os.getenv("DB_PATH")or"/tmp/bot_config.db"
db_lock=threading.Lock()
def get_db():
 conn=sqlite3.connect(DB_PATH,check_same_thread=False)
 conn.row_factory=sqlite3.Row
 return conn
def init_db():
 with db_lock:
  conn=get_db()
  conn.executescript('''
   CREATE TABLE IF NOT EXISTS api_keys(name TEXT PRIMARY KEY,key_value TEXT);
   CREATE TABLE IF NOT EXISTS custom_models(id TEXT PRIMARY KEY,name TEXT,provider TEXT,model_id TEXT,emoji TEXT,description TEXT,category TEXT);
   CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
   CREATE TABLE IF NOT EXISTS user_models(uid TEXT PRIMARY KEY,model_id TEXT);
   CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,action TEXT,details TEXT);
  ''')
  defaults={"default_model":"groq","system_prompt":"You are a helpful AI assistant.","rate_limit_ai":"5","max_memory_messages":"25","memory_timeout_minutes":"30"}
  for k,v in defaults.items():
   conn.execute('INSERT OR IGNORE INTO settings(key,value)VALUES(?,?)',(k,v))
  conn.commit()
  conn.close()
  print("✅ Database initialized")
def log_action(action,details=""):
 with db_lock:
  conn=get_db()
  conn.execute('INSERT INTO logs(action,details)VALUES(?,?)',(action,details))
  conn.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 100)')
  conn.commit()
  conn.close()
@asynccontextmanager
async def lifespan(app:FastAPI):
 init_db()
 print(f"🌐 Panel ready | User: {ADMIN_USER}")
 yield
app=FastAPI(docs_url=None,redoc_url=None,lifespan=lifespan)
security=HTTPBasic()
def get_key(name):
 with db_lock:
  conn=get_db()
  r=conn.execute('SELECT key_value FROM api_keys WHERE name=?',(name,)).fetchone()
  conn.close()
  return r['key_value']if r else None
def config():
 with db_lock:
  conn=get_db()
  keys={r['name']:r['key_value']for r in conn.execute('SELECT * FROM api_keys')}
  models={}
  for r in conn.execute('SELECT * FROM custom_models'):
   models[r['id']]={'e':r['emoji']or'🤖','n':r['name'],'d':r['description']or r['name'],'c':r['category']or'custom','p':r['provider'],'m':r['model_id']}
  settings={r['key']:r['value']for r in conn.execute('SELECT * FROM settings')}
  user_models={r['uid']:r['model_id']for r in conn.execute('SELECT * FROM user_models')}
  conn.close()
  return{"keys":keys,"models":models,"settings":settings,"user_models":user_models}
def auth_admin(c:HTTPBasicCredentials=Depends(security)):
 u_ok=secrets.compare_digest(c.username.encode(),ADMIN_USER.encode())
 p_ok=secrets.compare_digest(c.password.encode(),ADMIN_PASS.encode())
 if not(u_ok and p_ok):
  raise HTTPException(401,"Unauthorized",{"WWW-Authenticate":"Basic"})
 return c.username
def auth_bot(req:Request):
 secret=req.headers.get("X-Bot-Secret","")
 if not secret or not secrets.compare_digest(secret,BOT_SECRET):
  raise HTTPException(401,"Invalid Bot Secret")
@app.get("/")
def root():
 return RedirectResponse("/dash")
@app.get("/health")
def health():
 return{"status":"ok","admin":ADMIN_USER}
@app.get("/api/bot/config")
def api_config(req:Request):
 auth_bot(req)
 return config()
def page(title,content,active=""):
 nav=[("dash","📊","Dashboard"),("keys","🔑","API Keys"),("models","🤖","Models"),("users","👥","Users"),("settings","⚙️","Settings"),("logs","📋","Logs")]
 n="".join([f'<a href="/{k}" class="flex items-center gap-2 px-4 py-3 rounded-lg {"bg-blue-600 text-white" if k==active else "text-gray-300 hover:bg-gray-700"}">{e} {l}</a>'for k,e,l in nav])
 return f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} - Bot Panel</title><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-gray-900 text-white"><div class="flex min-h-screen"><aside class="w-64 bg-gray-800 p-4 space-y-2 hidden md:block"><h1 class="text-xl font-bold text-blue-400 mb-6 text-center">🤖 Bot Panel</h1>{n}</aside><main class="flex-1 p-6"><div class="md:hidden mb-4 flex gap-2 overflow-x-auto">{n}</div>{content}</main></div></body></html>'''
@app.get("/dash",response_class=HTMLResponse)
def dashboard(u:str=Depends(auth_admin)):
 c=config()
 h=f'''<h2 class="text-2xl font-bold mb-6">📊 Dashboard</h2>
 <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
  <div class="bg-gray-800 p-4 rounded-lg"><p class="text-gray-400">API Keys</p><p class="text-3xl font-bold text-green-400">{len(c["keys"])}</p></div>
  <div class="bg-gray-800 p-4 rounded-lg"><p class="text-gray-400">Custom Models</p><p class="text-3xl font-bold text-blue-400">{len(c["models"])}</p></div>
  <div class="bg-gray-800 p-4 rounded-lg"><p class="text-gray-400">User Configs</p><p class="text-3xl font-bold text-yellow-400">{len(c["user_models"])}</p></div>
  <div class="bg-gray-800 p-4 rounded-lg"><p class="text-gray-400">Default Model</p><p class="text-xl font-bold text-purple-400">{c["settings"].get("default_model","groq")}</p></div>
 </div>
 <div class="bg-gray-800 p-4 rounded-lg">
  <h3 class="font-bold mb-2">System Prompt</h3>
  <p class="text-gray-400 text-sm">{c["settings"].get("system_prompt","")[:200]}...</p>
 </div>'''
 return page("Dashboard",h,"dash")
@app.get("/keys",response_class=HTMLResponse)
def keys_page(u:str=Depends(auth_admin)):
 c=config()
 provs=["groq","openrouter","gemini","cerebras","sambanova","cohere","mistral","together","moonshot","huggingface","replicate","pollinations","tavily","cloudflare_account","cloudflare_token"]
 rows=""
 for p in provs:
  v=c['keys'].get(p,"")
  st="✅"if v else"❌"
  rows+=f'<div class="flex gap-2 items-center"><span class="w-6">{st}</span><label class="w-40 text-gray-300">{p}</label><input type="password" name="{p}" value="{v}" class="flex-1 bg-gray-700 border border-gray-600 rounded p-2" placeholder="Enter key..."></div>'
 h=f'''<h2 class="text-2xl font-bold mb-6">🔑 API Keys</h2>
 <form action="/keys" method="post" class="bg-gray-800 p-6 rounded-lg space-y-3">
  {rows}
  <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 py-3 rounded-lg font-bold mt-4">💾 Save Keys</button>
 </form>'''
 return page("API Keys",h,"keys")
@app.post("/keys")
async def save_keys(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("save_keys","Updated API keys")
 with db_lock:
  conn=get_db()
  for k,v in f.items():
   if v.strip():
    conn.execute('INSERT OR REPLACE INTO api_keys VALUES(?,?)',(k,v.strip()))
   else:
    conn.execute('DELETE FROM api_keys WHERE name=?',(k,))
  conn.commit()
  conn.close()
 return RedirectResponse("/keys",303)
@app.get("/models",response_class=HTMLResponse)
def models_page(u:str=Depends(auth_admin)):
 c=config()
 rows=""
 for k,m in c['models'].items():
  rows+=f'<tr class="border-b border-gray-700"><td class="py-2 text-blue-400">{k}</td><td>{m["e"]} {m["n"]}</td><td>{m["p"]}</td><td class="text-xs text-gray-400">{m["m"][:25]}...</td><td><form action="/models/del" method="post" class="inline"><input type="hidden" name="id" value="{k}"><button class="text-red-500 hover:text-red-400">🗑️</button></form></td></tr>'
 if not rows:
  rows='<tr><td colspan="5" class="py-4 text-center text-gray-500">No custom models</td></tr>'
 h=f'''<h2 class="text-2xl font-bold mb-6">🤖 Custom Models</h2>
 <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
  <div class="bg-gray-800 p-4 rounded-lg">
   <h3 class="font-bold mb-4">➕ Add Model</h3>
   <form action="/models/add" method="post" class="space-y-2">
    <input name="id" required placeholder="ID (ex: my_gpt)" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <input name="name" required placeholder="Name" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <select name="provider" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
     <option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="gemini">Gemini</option>
     <option value="cerebras">Cerebras</option><option value="sambanova">SambaNova</option><option value="together">Together</option>
     <option value="mistral">Mistral</option><option value="pollinations_free">Pollinations Free</option>
    </select>
    <input name="model_id" required placeholder="API Model ID" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <input name="description" placeholder="Description" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <input name="category" placeholder="Category" value="custom" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <input name="emoji" placeholder="Emoji" value="🤖" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <button type="submit" class="w-full bg-green-600 hover:bg-green-700 py-2 rounded font-bold">Add</button>
   </form>
  </div>
  <div class="lg:col-span-2 bg-gray-800 p-4 rounded-lg">
   <h3 class="font-bold mb-4">📋 Models List</h3>
   <table class="w-full text-sm"><thead><tr class="border-b border-gray-700"><th class="text-left py-2">ID</th><th class="text-left">Name</th><th class="text-left">Provider</th><th class="text-left">Model</th><th>Del</th></tr></thead><tbody>{rows}</tbody></table>
  </div>
 </div>'''
 return page("Models",h,"models")
@app.post("/models/add")
async def add_model(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("add_model",f"Added {f['id']}")
 with db_lock:
  conn=get_db()
  conn.execute('INSERT OR REPLACE INTO custom_models VALUES(?,?,?,?,?,?,?)',(f['id'],f['name'],f['provider'],f['model_id'],f.get('emoji','🤖'),f.get('description',''),f.get('category','custom')))
  conn.commit()
  conn.close()
 return RedirectResponse("/models",303)
@app.post("/models/del")
async def del_model(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("del_model",f"Deleted {f['id']}")
 with db_lock:
  conn=get_db()
  conn.execute('DELETE FROM custom_models WHERE id=?',(f['id'],))
  conn.commit()
  conn.close()
 return RedirectResponse("/models",303)
@app.get("/users",response_class=HTMLResponse)
def users_page(u:str=Depends(auth_admin)):
 c=config()
 rows=""
 for uid,mid in c['user_models'].items():
  rows+=f'<tr class="border-b border-gray-700"><td class="py-2 font-mono">{uid}</td><td class="text-blue-400">{mid}</td><td><form action="/users/del" method="post" class="inline"><input type="hidden" name="uid" value="{uid}"><button class="text-red-500">🗑️</button></form></td></tr>'
 if not rows:
  rows='<tr><td colspan="3" class="py-4 text-center text-gray-500">No user configs (all use default)</td></tr>'
 h=f'''<h2 class="text-2xl font-bold mb-6">👥 User Models</h2>
 <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
  <div class="bg-gray-800 p-4 rounded-lg">
   <h3 class="font-bold mb-4">➕ Set User Model</h3>
   <form action="/users/set" method="post" class="space-y-2">
    <input name="uid" required placeholder="Discord User ID" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <input name="model_id" required placeholder="Model ID (groq, gemini...)" class="w-full bg-gray-700 border border-gray-600 rounded p-2">
    <button type="submit" class="w-full bg-yellow-600 hover:bg-yellow-700 py-2 rounded font-bold">Set</button>
   </form>
  </div>
  <div class="lg:col-span-2 bg-gray-800 p-4 rounded-lg">
   <h3 class="font-bold mb-4">📋 User List</h3>
   <table class="w-full text-sm"><thead><tr class="border-b border-gray-700"><th class="text-left py-2">User ID</th><th class="text-left">Model</th><th>Del</th></tr></thead><tbody>{rows}</tbody></table>
  </div>
 </div>'''
 return page("Users",h,"users")
@app.post("/users/set")
async def set_user(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("set_user",f"{f['uid']}={f['model_id']}")
 with db_lock:
  conn=get_db()
  conn.execute('INSERT OR REPLACE INTO user_models VALUES(?,?)',(f['uid'],f['model_id']))
  conn.commit()
  conn.close()
 return RedirectResponse("/users",303)
@app.post("/users/del")
async def del_user(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("del_user",f"{f['uid']}")
 with db_lock:
  conn=get_db()
  conn.execute('DELETE FROM user_models WHERE uid=?',(f['uid'],))
  conn.commit()
  conn.close()
 return RedirectResponse("/users",303)
@app.get("/settings",response_class=HTMLResponse)
def settings_page(u:str=Depends(auth_admin)):
 c=config()
 s=c['settings']
 h=f'''<h2 class="text-2xl font-bold mb-6">⚙️ Settings</h2>
 <form action="/settings" method="post" class="bg-gray-800 p-6 rounded-lg space-y-4 max-w-2xl">
  <div><label class="block text-gray-400 mb-1">Default Model</label><input name="default_model" value="{s.get('default_model','groq')}" class="w-full bg-gray-700 border border-gray-600 rounded p-2"></div>
  <div><label class="block text-gray-400 mb-1">System Prompt</label><textarea name="system_prompt" rows="4" class="w-full bg-gray-700 border border-gray-600 rounded p-2">{s.get('system_prompt','')}</textarea></div>
  <div class="grid grid-cols-3 gap-4">
   <div><label class="block text-gray-400 mb-1">Rate Limit (s)</label><input type="number" name="rate_limit_ai" value="{s.get('rate_limit_ai','5')}" class="w-full bg-gray-700 border border-gray-600 rounded p-2"></div>
   <div><label class="block text-gray-400 mb-1">Max Memory</label><input type="number" name="max_memory_messages" value="{s.get('max_memory_messages','25')}" class="w-full bg-gray-700 border border-gray-600 rounded p-2"></div>
   <div><label class="block text-gray-400 mb-1">Timeout (min)</label><input type="number" name="memory_timeout_minutes" value="{s.get('memory_timeout_minutes','30')}" class="w-full bg-gray-700 border border-gray-600 rounded p-2"></div>
  </div>
  <button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 py-3 rounded-lg font-bold">💾 Save Settings</button>
 </form>'''
 return page("Settings",h,"settings")
@app.post("/settings")
async def save_settings(req:Request,u:str=Depends(auth_admin)):
 f=await req.form()
 log_action("save_settings","Updated")
 with db_lock:
  conn=get_db()
  for k,v in f.items():
   conn.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))
  conn.commit()
  conn.close()
 return RedirectResponse("/settings",303)
@app.get("/logs",response_class=HTMLResponse)
def logs_page(u:str=Depends(auth_admin)):
 with db_lock:
  conn=get_db()
  logs=conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 50').fetchall()
  conn.close()
 rows=""
 for l in logs:
  rows+=f'<tr class="border-b border-gray-700"><td class="py-2 text-gray-500 text-sm">{l["ts"]}</td><td class="text-blue-400">{l["action"]}</td><td>{l["details"]}</td></tr>'
 if not rows:
  rows='<tr><td colspan="3" class="py-4 text-center text-gray-500">No logs</td></tr>'
 h=f'''<h2 class="text-2xl font-bold mb-6">📋 Logs</h2>
 <div class="bg-gray-800 p-4 rounded-lg">
  <table class="w-full text-sm"><thead><tr class="border-b border-gray-700"><th class="text-left py-2">Time</th><th class="text-left">Action</th><th class="text-left">Details</th></tr></thead><tbody>{rows}</tbody></table>
 </div>'''
 return page("Logs",h,"logs")