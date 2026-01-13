from fastapi import FastAPI,HTTPException,Depends,Request,Form
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from fastapi.security import HTTPBasic,HTTPBasicCredentials
from contextlib import asynccontextmanager
import sqlite3,secrets,json,os,threading,time,logging
from datetime import datetime
from typing import Optional
ADMIN_USER=os.getenv("ADMIN_USER","admin")
ADMIN_PASS=os.getenv("ADMIN_PASS","admin123")
BOT_SECRET=os.getenv("CONFIG_BOT_SECRET","bot_secret_key_123")
DB_PATH=os.getenv("DB_PATH","bot_config.db")
db_lock=threading.Lock()
logger=logging.getLogger("uvicorn")
def get_db():conn=sqlite3.connect(DB_PATH,check_same_thread=False);conn.row_factory=sqlite3.Row;return conn
def init_db():
 with db_lock:
  conn=get_db()
  conn.executescript('''CREATE TABLE IF NOT EXISTS api_keys(name TEXT PRIMARY KEY,key_value TEXT);CREATE TABLE IF NOT EXISTS custom_models(id TEXT PRIMARY KEY,name TEXT,provider TEXT,model_id TEXT,emoji TEXT,description TEXT,category TEXT);CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS user_models(uid TEXT PRIMARY KEY,model_id TEXT);CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,action TEXT,details TEXT);''')
  defaults={"default_model":"groq","system_prompt":"You are a helpful AI assistant.","rate_limit_ai":"5","max_memory_messages":"25","memory_timeout_minutes":"30"}
  for k,v in defaults.items():conn.execute('INSERT OR IGNORE INTO settings(key,value)VALUES(?,?)',(k,v))
  conn.commit();conn.close()
def log_action(action,details):
 with db_lock:
  conn=get_db();conn.execute('INSERT INTO logs(action,details)VALUES(?,?)',(action,details))
  conn.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 100)');conn.commit();conn.close()
@asynccontextmanager
async def lifespan(app:FastAPI):init_db();yield
app=FastAPI(docs_url=None,redoc_url=None,lifespan=lifespan)
security=HTTPBasic()
def get_key(name):
 with db_lock:c=get_db();r=c.execute('SELECT key_value FROM api_keys WHERE name=?',(name,)).fetchone();c.close();return r['key_value']if r else None
def config():
 with db_lock:
  conn=get_db()
  keys={r['name']:r['key_value']for r in conn.execute('SELECT * FROM api_keys')}
  models={}
  for r in conn.execute('SELECT * FROM custom_models'):
   models[r['id']]={'e':r['emoji']or'🤖','n':r['name'],'d':r['description']or r['name'],'c':r['category']or'custom','p':r['provider'],'m':r['model_id']}
  settings={r['key']:r['value']for r in conn.execute('SELECT * FROM settings')}
  user_models={r['uid']:r['model_id']for r in conn.execute('SELECT * FROM user_models')}
  conn.close();return{"keys":keys,"models":models,"settings":settings,"user_models":user_models}
def auth_admin(c:HTTPBasicCredentials=Depends(security)):
 if not(secrets.compare_digest(c.username,ADMIN_USER)and secrets.compare_digest(c.password,ADMIN_PASS)):raise HTTPException(401,"Unauthorized",{"WWW-Authenticate":"Basic"})
 return c.username
def auth_bot(req:Request):
 if not secrets.compare_digest(req.headers.get("X-Bot-Secret",""),BOT_SECRET):raise HTTPException(401,"Invalid Secret")
@app.get("/api/bot/config")
def api_config(req:Request):auth_bot(req);return config()
def render(content,active="dash"):
 nav={"dash":"Dashboard","keys":"API Keys","models":"Custom Models","users":"User Models","settings":"Settings","logs":"Logs"}
 n_html="".join([f'<a href="/{k}" class="block py-2.5 px-4 rounded transition duration-200 {"bg-blue-600 text-white" if k==active else "hover:bg-gray-700 text-gray-300"}">{v}</a>' for k,v in nav.items()])
 return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Bot Admin Panel</title><script src="https://cdn.tailwindcss.com"></script><link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet"><style>body{{background-color:#111827;color:#f3f4f6}}</style></head><body class="flex h-screen overflow-hidden"><aside class="w-64 bg-gray-800 hidden md:block flex-shrink-0 border-r border-gray-700"><div class="p-6 text-center text-2xl font-bold text-blue-500 tracking-wider">🤖 CONTROL</div><nav class="mt-6 px-4 space-y-2">{n_html}</nav></aside><div class="flex-1 flex flex-col overflow-hidden"><header class="flex justify-between items-center py-4 px-6 bg-gray-800 border-b border-gray-700 md:hidden"><span class="text-xl font-bold text-blue-500">Panel</span><button onclick="document.querySelector('aside').classList.toggle('hidden')" class="text-gray-300"><i class="fas fa-bars"></i></button></header><main class="flex-1 overflow-x-hidden overflow-y-auto bg-gray-900 p-6">{content}</main></div></body></html>"""
@app.get("/",response_class=HTMLResponse)
@app.get("/dash",response_class=HTMLResponse)
def dashboard(u:str=Depends(auth_admin)):
 c=config();k_c=len(c['keys']);m_c=len(c['models']);u_c=len(c['user_models'])
 h=f"""<div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"><div class="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700"><div class="flex items-center"><div class="p-3 rounded-full bg-green-500 bg-opacity-20 text-green-500"><i class="fas fa-key fa-2x"></i></div><div class="ml-4"><p class="text-gray-400">API Keys</p><p class="text-2xl font-bold">{k_c}</p></div></div></div><div class="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700"><div class="flex items-center"><div class="p-3 rounded-full bg-blue-500 bg-opacity-20 text-blue-500"><i class="fas fa-robot fa-2x"></i></div><div class="ml-4"><p class="text-gray-400">Custom Models</p><p class="text-2xl font-bold">{m_c}</p></div></div></div><div class="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700"><div class="flex items-center"><div class="p-3 rounded-full bg-yellow-500 bg-opacity-20 text-yellow-500"><i class="fas fa-users fa-2x"></i></div><div class="ml-4"><p class="text-gray-400">User Configs</p><p class="text-2xl font-bold">{u_c}</p></div></div></div><div class="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700"><div class="flex items-center"><div class="p-3 rounded-full bg-purple-500 bg-opacity-20 text-purple-500"><i class="fas fa-cog fa-2x"></i></div><div class="ml-4"><p class="text-gray-400">Default</p><p class="text-xl font-bold">{c['settings'].get('default_model','groq')}</p></div></div></div></div><div class="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h3 class="text-xl font-bold mb-4">📋 Quick Info</h3><div class="grid grid-cols-1 md:grid-cols-2 gap-4"><div class="bg-gray-700 p-4 rounded"><span class="text-gray-400">System Prompt:</span><p class="mt-1 text-sm text-gray-300">{c['settings'].get('system_prompt','')[:100]}...</p></div><div class="bg-gray-700 p-4 rounded"><span class="text-gray-400">Rate Limit:</span><p class="mt-1 text-green-400">{c['settings'].get('rate_limit_ai','5')} seconds</p></div></div></div>"""
 return render(h,"dash")
@app.get("/keys",response_class=HTMLResponse)
def keys_page(u:str=Depends(auth_admin)):
 c=config();provs=["groq","openrouter","gemini","cerebras","sambanova","cohere","mistral","together","moonshot","huggingface","replicate","pollinations","tavily","cloudflare_account","cloudflare_token"]
 h=f"""<div class="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h2 class="text-2xl font-bold mb-6 flex items-center gap-2"><i class="fas fa-key text-yellow-500"></i> API Keys</h2><form action="/keys" method="post" class="grid grid-cols-1 md:grid-cols-2 gap-6">"""
 for p in provs:v=c['keys'].get(p,"");st="✅"if v else"❌";h+=f"""<div><label class="block text-gray-400 text-sm font-bold mb-2">{st} {p.replace('_',' ').title()}</label><input type="password" name="{p}" value="{v}" class="w-full bg-gray-700 text-white border border-gray-600 rounded py-2 px-3 focus:outline-none focus:border-blue-500" placeholder="Enter key..."></div>"""
 h+=f"""<div class="col-span-1 md:col-span-2"><button type="submit" class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-6 rounded w-full"><i class="fas fa-save mr-2"></i>Save Keys</button></div></form></div>"""
 return render(h,"keys")
@app.post("/keys")
async def save_keys(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("update_keys",f"Updated keys")
 with db_lock:
  conn=get_db()
  for k,v in f.items():
   if v.strip():conn.execute('INSERT OR REPLACE INTO api_keys VALUES(?,?)',(k,v.strip()))
   else:conn.execute('DELETE FROM api_keys WHERE name=?',(k,))
  conn.commit();conn.close()
 return RedirectResponse("/keys",303)
@app.get("/models",response_class=HTMLResponse)
def models_page(u:str=Depends(auth_admin)):
 c=config()
 h=f"""<div class="grid grid-cols-1 lg:grid-cols-3 gap-6"><div class="lg:col-span-1 bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h3 class="text-xl font-bold mb-4">➕ Add Model</h3><form action="/models/add" method="post" class="space-y-3"><input type="text" name="id" required placeholder="ID (ex: my_gpt)" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><input type="text" name="name" required placeholder="Name (ex: My GPT)" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><select name="provider" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="gemini">Gemini</option><option value="cerebras">Cerebras</option><option value="sambanova">SambaNova</option><option value="together">Together</option><option value="mistral">Mistral</option><option value="cohere">Cohere</option><option value="pollinations_free">Pollinations Free</option><option value="pollinations_api">Pollinations API</option></select><input type="text" name="model_id" required placeholder="API Model ID" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><input type="text" name="description" placeholder="Description" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><select name="category" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><option value="custom">Custom</option><option value="main">Main</option><option value="openrouter">OpenRouter</option><option value="gemini">Gemini</option></select><input type="text" name="emoji" value="🤖" placeholder="Emoji" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><button type="submit" class="w-full bg-green-600 hover:bg-green-700 py-2 rounded font-bold">Add</button></form></div><div class="lg:col-span-2 bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h3 class="text-xl font-bold mb-4">📋 Custom Models</h3><div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr class="border-b border-gray-700"><th class="py-2">ID</th><th class="py-2">Name</th><th class="py-2">Provider</th><th class="py-2">Model</th><th class="py-2">Cat</th><th class="py-2">Del</th></tr></thead><tbody>"""
 if not c['models']:h+=f"""<tr><td colspan="6" class="py-4 text-center text-gray-500">No custom models</td></tr>"""
 else:
  for k,m in c['models'].items():h+=f"""<tr class="border-b border-gray-700"><td class="py-2 text-blue-400">{k}</td><td class="py-2">{m['e']} {m['n']}</td><td class="py-2">{m['p']}</td><td class="py-2 text-xs text-gray-400">{m['m'][:20]}...</td><td class="py-2">{m['c']}</td><td class="py-2"><form action="/models/del" method="post" style="display:inline"><input type="hidden" name="id" value="{k}"><button class="text-red-500 hover:text-red-400">🗑️</button></form></td></tr>"""
 h+="</tbody></table></div></div></div>";return render(h,"models")
@app.post("/models/add")
async def add_model(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("add_model",f"Added {f['id']}")
 with db_lock:c=get_db();c.execute('INSERT OR REPLACE INTO custom_models VALUES(?,?,?,?,?,?,?)',(f['id'],f['name'],f['provider'],f['model_id'],f['emoji'],f['description'],f['category']));c.commit();c.close()
 return RedirectResponse("/models",303)
@app.post("/models/del")
async def del_model(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("del_model",f"Deleted {f['id']}")
 with db_lock:c=get_db();c.execute('DELETE FROM custom_models WHERE id=?',(f['id'],));c.commit();c.close()
 return RedirectResponse("/models",303)
@app.get("/users",response_class=HTMLResponse)
def users_page(u:str=Depends(auth_admin)):
 c=config()
 h=f"""<div class="grid grid-cols-1 lg:grid-cols-3 gap-6"><div class="lg:col-span-1 bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h3 class="text-xl font-bold mb-4">👤 Set User Model</h3><form action="/users/set" method="post" class="space-y-3"><input type="text" name="uid" required placeholder="Discord User ID" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><input type="text" name="model_id" required placeholder="Model ID (ex: groq, gemini)" class="w-full bg-gray-700 border border-gray-600 rounded p-2"><button type="submit" class="w-full bg-yellow-600 hover:bg-yellow-700 py-2 rounded font-bold">Set Model</button></form></div><div class="lg:col-span-2 bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h3 class="text-xl font-bold mb-4">📋 User Model Assignments</h3><div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr class="border-b border-gray-700"><th class="py-2">User ID</th><th class="py-2">Model</th><th class="py-2">Remove</th></tr></thead><tbody>"""
 if not c['user_models']:h+=f"""<tr><td colspan="3" class="py-4 text-center text-gray-500">No user assignments (all use default)</td></tr>"""
 else:
  for uid,mid in c['user_models'].items():h+=f"""<tr class="border-b border-gray-700"><td class="py-2 font-mono">{uid}</td><td class="py-2 text-blue-400">{mid}</td><td class="py-2"><form action="/users/del" method="post" style="display:inline"><input type="hidden" name="uid" value="{uid}"><button class="text-red-500">🗑️</button></form></td></tr>"""
 h+="</tbody></table></div></div></div>";return render(h,"users")
@app.post("/users/set")
async def set_user(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("set_user_model",f"{f['uid']}={f['model_id']}")
 with db_lock:c=get_db();c.execute('INSERT OR REPLACE INTO user_models VALUES(?,?)',(f['uid'],f['model_id']));c.commit();c.close()
 return RedirectResponse("/users",303)
@app.post("/users/del")
async def del_user(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("del_user_model",f"{f['uid']}")
 with db_lock:c=get_db();c.execute('DELETE FROM user_models WHERE uid=?',(f['uid'],));c.commit();c.close()
 return RedirectResponse("/users",303)
@app.get("/settings",response_class=HTMLResponse)
def settings_page(u:str=Depends(auth_admin)):
 c=config();s=c['settings']
 h=f"""<div class="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6 max-w-2xl mx-auto"><h2 class="text-2xl font-bold mb-6"><i class="fas fa-cog text-purple-500"></i> Settings</h2><form action="/settings" method="post" class="space-y-6"><div><label class="block text-gray-400 mb-2">Default Model</label><input type="text" name="default_model" value="{s.get('default_model','groq')}" class="w-full bg-gray-700 border border-gray-600 rounded p-3" placeholder="groq, gemini, or_llama, etc"></div><div><label class="block text-gray-400 mb-2">System Prompt</label><textarea name="system_prompt" rows="4" class="w-full bg-gray-700 border border-gray-600 rounded p-3">{s.get('system_prompt','')}</textarea></div><div class="grid grid-cols-3 gap-4"><div><label class="block text-gray-400 mb-2">Rate Limit (s)</label><input type="number" name="rate_limit_ai" value="{s.get('rate_limit_ai','5')}" class="w-full bg-gray-700 border border-gray-600 rounded p-3"></div><div><label class="block text-gray-400 mb-2">Max Memory</label><input type="number" name="max_memory_messages" value="{s.get('max_memory_messages','25')}" class="w-full bg-gray-700 border border-gray-600 rounded p-3"></div><div><label class="block text-gray-400 mb-2">Timeout (min)</label><input type="number" name="memory_timeout_minutes" value="{s.get('memory_timeout_minutes','30')}" class="w-full bg-gray-700 border border-gray-600 rounded p-3"></div></div><button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 py-3 rounded font-bold">Save</button></form></div>"""
 return render(h,"settings")
@app.post("/settings")
async def save_settings(req:Request,u:str=Depends(auth_admin)):
 f=await req.form();log_action("update_settings","Updated")
 with db_lock:c=get_db();[c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))for k,v in f.items()];c.commit();c.close()
 return RedirectResponse("/settings",303)
@app.get("/logs",response_class=HTMLResponse)
def logs_page(u:str=Depends(auth_admin)):
 with db_lock:c=get_db();l=c.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 50').fetchall();c.close()
 h=f"""<div class="bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-6"><h2 class="text-2xl font-bold mb-6"><i class="fas fa-list text-gray-400"></i> Logs</h2><table class="w-full text-left text-sm"><thead><tr class="border-b border-gray-700"><th class="py-2">Time</th><th class="py-2">Action</th><th class="py-2">Details</th></tr></thead><tbody>"""
 for r in l:h+=f"""<tr class="border-b border-gray-700"><td class="py-2 text-gray-500">{r['ts']}</td><td class="py-2 text-blue-400">{r['action']}</td><td class="py-2">{r['details']}</td></tr>"""
 h+="</tbody></table></div>";return render(h,"logs")
def start_web_panel(host="0.0.0.0",port=8080,admin_key="admin123"):
 import uvicorn;global ADMIN_PASS;ADMIN_PASS=admin_key;uvicorn.run(app,host=host,port=port,log_level="error")
if __name__=="__main__":start_web_panel()
