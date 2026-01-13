from fastapi import FastAPI,HTTPException,Depends,Request,Form
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.security import HTTPBasic,HTTPBasicCredentials
from contextlib import asynccontextmanager
import sqlite3,secrets,os,threading,json

# --- 40+ MODEL LENGKAP (Fixed) ---
DEFAULT_MODELS = {
    # GROQ
    "groq":{"e":"⚡","n":"Groq","d":"Llama 3.3 70B","c":"main","p":"groq","m":"llama-3.3-70b-versatile"},
    "groq_8b":{"e":"⚡","n":"Groq-8B","d":"Llama 3.1 8B","c":"main","p":"groq","m":"llama-3.1-8b-instant"},
    "groq_mav":{"e":"🦙","n":"Groq-Maverick","d":"Llama 4 Maverick","c":"main","p":"groq","m":"meta-llama/llama-4-maverick-17b-128e-instruct"},
    "groq_scout":{"e":"🔍","n":"Groq-Scout","d":"Llama 4 Scout","c":"main","p":"groq","m":"meta-llama/llama-4-scout-17b-16e-instruct"},
    "groq_guard":{"e":"🛡️","n":"Groq-Guard","d":"Llama Guard 4","c":"main","p":"groq","m":"meta-llama/llama-guard-4-12b"},
    "groq_guard_p":{"e":"🛡️","n":"Groq-Prompt Guard","d":"Prompt Guard 86M","c":"main","p":"groq","m":"meta-llama/llama-prompt-guard-2-86m"},
    "groq_kimi":{"e":"🌙","n":"Groq-Kimi","d":"Kimi K2 Instruct","c":"main","p":"groq","m":"moonshotai/kimi-k2-instruct"},
    "groq_gpt120":{"e":"🤖","n":"Groq-GPT120","d":"GPT OSS 120B","c":"main","p":"groq","m":"openai/gpt-oss-120b"},
    "groq_gpt20":{"e":"🤖","n":"Groq-GPT20","d":"GPT OSS 20B","c":"main","p":"groq","m":"openai/gpt-oss-20b"},
    "groq_whisper":{"e":"🎙️","n":"Groq-Whisper","d":"Whisper Large V3","c":"main","p":"groq","m":"whisper-large-v3"},
    
    # GEMINI
    "gemini_flash":{"e":"💎","n":"Gemini Flash","d":"2.0 Flash Lite","c":"gemini","p":"gemini","m":"gemini-2.0-flash-lite"},
    "gemini_lite":{"e":"💎","n":"Gemini Lite","d":"Flash Lite Latest","c":"gemini","p":"gemini","m":"gemini-flash-lite-latest"},
    "gemini_robot":{"e":"🤖","n":"Gemini Robot","d":"Robotics Preview","c":"gemini","p":"gemini","m":"gemini-robotics-er-1.5-preview"},

    # OPENROUTER (FREE)
    "or_llama":{"e":"🦙","n":"OR-Llama","d":"Llama 3.3 70B","c":"openrouter","p":"openrouter","m":"meta-llama/llama-3.3-70b-instruct:free"},
    "or_gemini":{"e":"💎","n":"OR-Gemini","d":"Gemini 2.0 Flash","c":"openrouter","p":"openrouter","m":"google/gemini-2.0-flash-exp:free"},
    "or_molmo":{"e":"👁️","n":"OR-Molmo","d":"Molmo2 8B","c":"openrouter","p":"openrouter","m":"allenai/molmo-2-8b:free"},
    "or_mimo":{"e":"🎭","n":"OR-MiMo","d":"MiMo V2 Flash","c":"openrouter","p":"openrouter","m":"xiaomi/mimo-v2-flash:free"},
    "or_nemotron":{"e":"🔥","n":"OR-Nemotron","d":"Nemotron 3 Nano","c":"openrouter","p":"openrouter","m":"nvidia/nemotron-3-nano-30b-a3b:free"},
    "or_devstral":{"e":"💻","n":"OR-Devstral","d":"Devstral 2","c":"openrouter","p":"openrouter","m":"mistralai/devstral-2-2512:free"},
    "or_trinity":{"e":"🔺","n":"OR-Trinity","d":"Trinity Mini","c":"openrouter","p":"openrouter","m":"trinity/trinity-mini:free"},
    "or_glm":{"e":"🇨🇳","n":"OR-GLM","d":"GLM 4.5 Air","c":"openrouter","p":"openrouter","m":"zhipu/glm-4.5-air:free"},
    "or_kimi":{"e":"🌙","n":"OR-Kimi","d":"Kimi K2","c":"openrouter","p":"openrouter","m":"moonshot/kimi-k2-0711:free"},
    "or_uncensored":{"e":"🔓","n":"OR-Uncensored","d":"Uncensored","c":"openrouter","p":"openrouter","m":"undi95/uncensored:free"},
    "or_r1":{"e":"🧠","n":"OR-DeepSeek R1","d":"R1 0528","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-r1-0528:free"},
    "or_r1t":{"e":"🧠","n":"OR-R1T Chimera","d":"R1T Chimera","c":"openrouter","p":"openrouter","m":"deepseek/r1t-chimera:free"},
    "or_r1t2":{"e":"🧠","n":"OR-R1T2 Chimera","d":"DeepSeek R1T2","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-r1t2-chimera:free"},

    # POLLINATIONS (FREE/API)
    "pf_openai":{"e":"🆓","n":"PollFree-OpenAI","d":"GPT-5 Mini","c":"pollinations_free","p":"pollinations_free","m":"openai"},
    "pf_fast":{"e":"⚡","n":"PollFree-Fast","d":"GPT-5 Nano","c":"pollinations_free","p":"pollinations_free","m":"openai-fast"},
    "pf_nova":{"e":"🚀","n":"PollFree-Nova","d":"Amazon Nova","c":"pollinations_free","p":"pollinations_free","m":"nova-fast"},
    "pf_mistral":{"e":"Ⓜ️","n":"PollFree-Mistral","d":"Mistral 3.2","c":"pollinations_free","p":"pollinations_free","m":"mistral"},
    "pf_gemini":{"e":"💎","n":"PollFree-Gemini","d":"Gemini 2.5 Lite","c":"pollinations_free","p":"pollinations_free","m":"gemini-fast"},
    "pf_qwen":{"e":"🔮","n":"PollFree-Qwen","d":"Qwen3 Coder","c":"pollinations_free","p":"pollinations_free","m":"qwen-coder"},
    "pf_deepseek":{"e":"🌊","n":"PollFree-DeepSeek","d":"DeepSeek V3.2","c":"pollinations_free","p":"pollinations_free","m":"deepseek"},
    "pf_grok":{"e":"❌","n":"PollFree-Grok","d":"Grok 4 Fast","c":"pollinations_free","p":"pollinations_free","m":"grok"},
    "pf_sonar":{"e":"🔍","n":"PollFree-Sonar","d":"Perplexity Sonar","c":"pollinations_free","p":"pollinations_free","m":"sonar"},
    "poll_free":{"e":"🌸","n":"PollFree-Auto","d":"Auto Free","c":"pollinations_free","p":"pollinations_free","m":"auto"}
}

DEFAULT_KEYS = {
    "groq": os.getenv("GROQ_API_KEY",""),
    "openrouter": os.getenv("OPENROUTER_API_KEY",""),
    "gemini": os.getenv("GEMINI_API_KEY",""),
    "cerebras": os.getenv("CEREBRAS_API_KEY",""),
    "sambanova": os.getenv("SAMBANOVA_API_KEY",""),
    "mistral": os.getenv("MISTRAL_API_KEY",""),
    "together": os.getenv("TOGETHER_API_KEY",""),
    "pollinations": os.getenv("POLLINATIONS_API_KEY","")
}

ADMIN_USER=os.getenv("ADMIN_USER")or"admin"
ADMIN_PASS=os.getenv("ADMIN_PASS")or os.getenv("ADMIN_KEY")or"admin123"
BOT_SECRET=os.getenv("BOT_SECRET")or os.getenv("CONFIG_BOT_SECRET")or"bot_secret_123"
DB_PATH="/tmp/bot_config.db"
db_lock=threading.Lock()

def get_db():
    conn=sqlite3.connect(DB_PATH,check_same_thread=False)
    conn.row_factory=sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn=get_db()
        conn.executescript('''CREATE TABLE IF NOT EXISTS api_keys(name TEXT PRIMARY KEY,key_value TEXT);CREATE TABLE IF NOT EXISTS custom_models(id TEXT PRIMARY KEY,name TEXT,provider TEXT,model_id TEXT,emoji TEXT,description TEXT,category TEXT);CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS user_models(uid TEXT PRIMARY KEY,model_id TEXT);CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,action TEXT,details TEXT);''')
        if conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] == 0:
            for k,v in DEFAULT_KEYS.items():
                if v: conn.execute("INSERT OR IGNORE INTO api_keys VALUES(?,?)",(k,v))
        if conn.execute("SELECT COUNT(*) FROM custom_models").fetchone()[0] == 0:
            for k,m in DEFAULT_MODELS.items():
                conn.execute("INSERT OR IGNORE INTO custom_models VALUES(?,?,?,?,?,?,?)",(k, m['n'], m['p'], m['m'], m['e'], m['d'], m['c']))
        defaults={"default_model":"groq","system_prompt":"You are a helpful AI assistant.","rate_limit_ai":"5","max_memory_messages":"25","memory_timeout_minutes":"30"}
        for k,v in defaults.items():
            conn.execute('INSERT OR IGNORE INTO settings(key,value)VALUES(?,?)',(k,v))
        conn.commit();conn.close()

def log_action(action,details=""):
    with db_lock:conn=get_db();conn.execute('INSERT INTO logs(action,details)VALUES(?,?)',(action,details));conn.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 100)');conn.commit();conn.close()

@asynccontextmanager
async def lifespan(app:FastAPI):init_db();yield

app=FastAPI(docs_url=None,redoc_url=None,lifespan=lifespan)
security=HTTPBasic()

def get_key(name):
    with db_lock:conn=get_db();r=conn.execute('SELECT key_value FROM api_keys WHERE name=?',(name,)).fetchone();conn.close();return r['key_value']if r else None

def config():
    with db_lock:
        conn=get_db()
        keys={r['name']:r['key_value']for r in conn.execute('SELECT * FROM api_keys')}
        models={}
        for r in conn.execute('SELECT * FROM custom_models'):models[r['id']]={'e':r['emoji']or'🤖','n':r['name'],'d':r['description']or r['name'],'c':r['category']or'custom','p':r['provider'],'m':r['model_id']}
        settings={r['key']:r['value']for r in conn.execute('SELECT * FROM settings')}
        user_models={r['uid']:r['model_id']for r in conn.execute('SELECT * FROM user_models')}
        conn.close()
        return{"keys":keys,"models":models,"settings":settings,"user_models":user_models}

def auth_admin(c:HTTPBasicCredentials=Depends(security)):
    if not(secrets.compare_digest(c.username.encode(),ADMIN_USER.encode())and secrets.compare_digest(c.password.encode(),ADMIN_PASS.encode())):raise HTTPException(401,"Unauthorized",{"WWW-Authenticate":"Basic"})
    return c.username

def auth_bot(req:Request):
    if not secrets.compare_digest(req.headers.get("X-Bot-Secret",""),BOT_SECRET):raise HTTPException(401,"Invalid Secret")

@app.get("/")
def root():return RedirectResponse("/dash")
@app.get("/health")
def health():return{"status":"ok","admin":ADMIN_USER}
@app.get("/api/bot/config")
def api_config(req:Request):auth_bot(req);return config()

def page(title,content,active=""):
    nav=[("dash","📊","Dashboard"),("keys","🔑","API Keys"),("models","🤖","Models"),("users","👥","Users"),("settings","⚙️","Settings"),("logs","📋","Logs")]
    n="".join([f'<a href="/{k}" class="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 {"bg-blue-600 shadow-lg shadow-blue-500/30 text-white" if k==active else "text-gray-400 hover:bg-gray-800 hover:text-white"}"><span class="text-lg">{e}</span> <span class="font-medium">{l}</span></a>'for k,e,l in nav])
    return f'''<!DOCTYPE html><html class="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} - Panel</title><script src="https://cdn.tailwindcss.com"></script><style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');body{{font-family:'Inter',sans-serif}}::-webkit-scrollbar{{width:8px}}::-webkit-scrollbar-track{{background:#111827}}::-webkit-scrollbar-thumb{{background:#374151;border-radius:4px}}</style><script>tailwind.config={{darkMode:'class',theme:{{extend:{{colors:{{dark:{{900:'#0f172a',800:'#1e293b',700:'#334155'}}}}}}}}}}</script></head><body class="bg-dark-900 text-gray-100"><div class="flex min-h-screen"><aside class="w-72 bg-dark-800 border-r border-dark-700 fixed h-full hidden md:flex flex-col"><div class="p-6 border-b border-dark-700"><h1 class="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Bot Panel</h1><p class="text-xs text-gray-500 mt-1">v2.0 Pro</p></div><nav class="flex-1 p-4 space-y-2 overflow-y-auto">{n}</nav></aside><main class="flex-1 md:ml-72 p-8"><header class="flex justify-between items-center mb-8 md:hidden"><h1 class="text-xl font-bold">Bot Panel</h1></header>{content}</main></div></body></html>'''

@app.get("/dash",response_class=HTMLResponse)
def dashboard(u:str=Depends(auth_admin)):
    c=config();h=f'''<div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 shadow-xl"><p class="text-gray-400 text-sm">Keys</p><p class="text-3xl font-bold text-green-400">{len(c["keys"])}</p></div><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 shadow-xl"><p class="text-gray-400 text-sm">Models</p><p class="text-3xl font-bold text-blue-400">{len(c["models"])}</p></div><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 shadow-xl"><p class="text-gray-400 text-sm">Users</p><p class="text-3xl font-bold text-yellow-400">{len(c["user_models"])}</p></div><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 shadow-xl"><p class="text-gray-400 text-sm">Active</p><p class="text-xl font-bold text-purple-400">{c["settings"].get("default_model","groq")}</p></div></div>'''
    return page("Dashboard",h,"dash")

@app.get("/keys",response_class=HTMLResponse)
def keys_page(u:str=Depends(auth_admin)):
    c=config();provs=["groq","openrouter","gemini","cerebras","sambanova","cohere","mistral","together","moonshot","pollinations","tavily","cloudflare_account","cloudflare_token"]
    rows=""
    for p in provs:v=c['keys'].get(p,"");st='<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>' if v else '<span class="w-2 h-2 rounded-full bg-red-500"></span>';rows+=f'<div class="group relative"><div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">{st}</div><input type="password" name="{p}" value="{v}" class="block w-full pl-8 pr-3 py-3 bg-dark-900 border border-dark-700 rounded-xl focus:ring-2 focus:ring-blue-500 transition-all text-sm" placeholder="{p.title()}"></div>'
    h=f'''<div class="max-w-4xl mx-auto"><h2 class="text-3xl font-bold mb-8">API Keys</h2><form action="/keys" method="post" class="bg-dark-800 p-8 rounded-2xl border border-dark-700 shadow-xl"><div class="grid grid-cols-1 md:grid-cols-2 gap-6">{rows}</div><div class="mt-8 pt-6 border-t border-dark-700 flex justify-end gap-4"><button type="submit" formaction="/keys/sync" class="px-6 py-3 text-blue-400 hover:text-white transition-colors">Sync Env</button><button type="submit" class="px-8 py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl shadow-lg transition-all">Save</button></div></form></div>'''
    return page("API Keys",h,"keys")

@app.post("/keys")
async def save_keys(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("save_keys","Updated API keys");with db_lock:conn=get_db();[conn.execute('INSERT OR REPLACE INTO api_keys VALUES(?,?)',(k,v.strip())) if v.strip() else conn.execute('DELETE FROM api_keys WHERE name=?',(k,)) for k,v in f.items()];conn.commit();conn.close()
    return RedirectResponse("/keys",303)

@app.post("/keys/sync")
async def sync_keys(u:str=Depends(auth_admin)):
    log_action("sync_keys","Synced from Environment");with db_lock:conn=get_db();[conn.execute('INSERT OR REPLACE INTO api_keys VALUES(?,?)',(k,v)) for k,v in DEFAULT_KEYS.items() if v];conn.commit();conn.close()
    return RedirectResponse("/keys",303)

@app.get("/models",response_class=HTMLResponse)
def models_page(u:str=Depends(auth_admin)):
    c=config();rows=""
    for k,m in c['models'].items():rows+=f'<tr class="border-b border-dark-700 hover:bg-dark-700/50 transition-colors"><td class="py-4 px-4 font-mono text-blue-400 text-sm">{k}</td><td class="py-4 px-4"><span class="text-xl mr-2">{m["e"]}</span>{m["n"]}</td><td class="py-4 px-4"><span class="px-2 py-1 bg-dark-900 rounded-lg text-xs border border-dark-600">{m["p"]}</span></td><td class="py-4 px-4 text-sm text-gray-400 font-mono">{m["m"][:20]}...</td><td class="py-4 px-4"><form action="/models/del" method="post"><input type="hidden" name="id" value="{k}"><button class="text-red-500 hover:text-white transition-colors">🗑️</button></form></td></tr>'
    h=f'''<div class="space-y-8"><div class="flex justify-between items-center"><h2 class="text-3xl font-bold">Models</h2><form action="/models/reset" method="post"><button class="px-4 py-2 bg-red-500/10 text-red-500 hover:bg-red-500 hover:text-white rounded-xl border border-red-500/20 transition-all text-sm font-bold">⚠️ Reset Defaults ({len(DEFAULT_MODELS)} Models)</button></form></div><div class="grid grid-cols-1 lg:grid-cols-3 gap-8"><div class="lg:col-span-1"><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 sticky top-4"><h3 class="font-bold mb-6 text-lg">➕ Add Model</h3><form action="/models/add" method="post" class="space-y-4"><input name="id" required placeholder="Unique ID (ex: my_gpt)" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"><input name="name" required placeholder="Display Name" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"><div class="grid grid-cols-2 gap-4"><select name="provider" class="bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm"><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="gemini">Gemini</option><option value="pollinations_free">PollFree</option></select><input name="emoji" placeholder="Emoji" value="🤖" class="bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm text-center"></div><input name="model_id" required placeholder="API Model ID" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm font-mono"><button type="submit" class="w-full bg-blue-600 hover:bg-blue-500 py-3 rounded-xl font-bold shadow-lg shadow-blue-500/20 transition-all">Add Model</button></form></div></div><div class="lg:col-span-2"><div class="bg-dark-800 rounded-2xl border border-dark-700 overflow-hidden"><table class="w-full text-left"><thead><tr class="bg-dark-900/50 border-b border-dark-700"><th class="py-4 px-4 font-medium text-gray-400 text-sm">ID</th><th class="py-4 px-4 font-medium text-gray-400 text-sm">Name</th><th class="py-4 px-4 font-medium text-gray-400 text-sm">Provider</th><th class="py-4 px-4 font-medium text-gray-400 text-sm">Model ID</th><th class="py-4 px-4"></th></tr></thead><tbody>{rows}</tbody></table></div></div></div></div>'''
    return page("Models",h,"models")

@app.post("/models/add")
async def add_model(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("add_model",f"Added {f['id']}");with db_lock:conn=get_db();conn.execute('INSERT OR REPLACE INTO custom_models VALUES(?,?,?,?,?,?,?)',(f['id'],f['name'],f['provider'],f['model_id'],f.get('emoji','🤖'),f.get('description',''),f.get('category','custom')));conn.commit();conn.close()
    return RedirectResponse("/models",303)

@app.post("/models/del")
async def del_model(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("del_model",f"Deleted {f['id']}");with db_lock:conn=get_db();conn.execute('DELETE FROM custom_models WHERE id=?',(f['id'],));conn.commit();conn.close()
    return RedirectResponse("/models",303)

@app.post("/models/reset")
async def reset_models(u:str=Depends(auth_admin)):
    with db_lock:conn=get_db();conn.execute('DELETE FROM custom_models');[conn.execute("INSERT INTO custom_models VALUES(?,?,?,?,?,?,?)",(k,m['n'],m['p'],m['m'],m['e'],m['d'],m['c'])) for k,m in DEFAULT_MODELS.items()];conn.commit();conn.close()
    return RedirectResponse("/models",303)

@app.get("/users",response_class=HTMLResponse)
def users_page(u:str=Depends(auth_admin)):
    c=config();rows=""
    for uid,mid in c['user_models'].items():rows+=f'<tr class="border-b border-dark-700"><td class="py-4 px-4 font-mono text-gray-300">{uid}</td><td class="py-4 px-4"><span class="px-2 py-1 bg-blue-500/10 text-blue-400 rounded border border-blue-500/20 text-sm">{mid}</span></td><td class="py-4 px-4"><form action="/users/del" method="post"><input type="hidden" name="uid" value="{uid}"><button class="text-red-500 hover:text-white transition-colors">✕</button></form></td></tr>'
    h=f'''<div class="max-w-5xl mx-auto space-y-8"><h2 class="text-3xl font-bold">User Management</h2><div class="grid grid-cols-1 md:grid-cols-3 gap-8"><div class="bg-dark-800 p-6 rounded-2xl border border-dark-700 h-fit"><h3 class="font-bold mb-4 text-lg">Set User Model</h3><form action="/users/set" method="post" class="space-y-4"><input name="uid" required placeholder="Discord User ID" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"><input name="model_id" required placeholder="Model ID (ex: groq)" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"><button type="submit" class="w-full bg-yellow-600 hover:bg-yellow-500 py-3 rounded-xl font-bold text-black shadow-lg shadow-yellow-500/20 transition-all">Assign Model</button></form></div><div class="md:col-span-2 bg-dark-800 rounded-2xl border border-dark-700 overflow-hidden"><table class="w-full text-left"><thead><tr class="bg-dark-900/50 border-b border-dark-700"><th class="py-4 px-4 text-sm font-medium text-gray-400">User ID</th><th class="py-4 px-4 text-sm font-medium text-gray-400">Assigned Model</th><th class="py-4 px-4"></th></tr></thead><tbody>{rows}</tbody></table></div></div></div>'''
    return page("Users",h,"users")

@app.post("/users/set")
async def set_user(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("set_user",f"{f['uid']}={f['model_id']}");with db_lock:conn=get_db();conn.execute('INSERT OR REPLACE INTO user_models VALUES(?,?)',(f['uid'],f['model_id']));conn.commit();conn.close()
    return RedirectResponse("/users",303)

@app.post("/users/del")
async def del_user(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("del_user",f"{f['uid']}");with db_lock:conn=get_db();conn.execute('DELETE FROM user_models WHERE uid=?',(f['uid'],));conn.commit();conn.close()
    return RedirectResponse("/users",303)

@app.get("/settings",response_class=HTMLResponse)
def settings_page(u:str=Depends(auth_admin)):
    c=config();s=c['settings'];models=c['models'];grps={};
    for k,m in models.items():p=m['p'];grps.setdefault(p,[]).append((k,m))
    opts=""
    for p,items in grps.items():
        opts+=f'<optgroup label="{p.upper()}">'
        for k,m in items:opts+=f'<option value="{k}" {"selected" if k==s.get("default_model") else ""}>{m["e"]} {m["n"]}</option>'
        opts+='</optgroup>'
    h=f'''<div class="max-w-3xl mx-auto"><h2 class="text-3xl font-bold mb-8">System Settings</h2><form action="/settings" method="post" class="bg-dark-800 p-8 rounded-2xl border border-dark-700 shadow-xl space-y-6"><div><label class="block text-gray-400 mb-2 font-medium">Default Model</label><select name="default_model" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none">{opts}</select></div><div><label class="block text-gray-400 mb-2 font-medium">System Prompt</label><textarea name="system_prompt" rows="5" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none leading-relaxed">{s.get('system_prompt','')}</textarea></div><div class="grid grid-cols-3 gap-6"><div><label class="block text-gray-400 mb-2 text-sm">Rate Limit (s)</label><input type="number" name="rate_limit_ai" value="{s.get('rate_limit_ai','5')}" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-center font-mono"></div><div><label class="block text-gray-400 mb-2 text-sm">Max Memory</label><input type="number" name="max_memory_messages" value="{s.get('max_memory_messages','25')}" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-center font-mono"></div><div><label class="block text-gray-400 mb-2 text-sm">Timeout (min)</label><input type="number" name="memory_timeout_minutes" value="{s.get('memory_timeout_minutes','30')}" class="w-full bg-dark-900 border border-dark-600 rounded-xl p-3 text-center font-mono"></div></div><div class="pt-6 border-t border-dark-700"><button type="submit" class="w-full bg-purple-600 hover:bg-purple-500 py-3 rounded-xl font-bold shadow-lg shadow-purple-500/20 transition-all">Save Changes</button></div></form></div>'''
    return page("Settings",h,"settings")

@app.post("/settings")
async def save_settings(req:Request,u:str=Depends(auth_admin)):
    f=await req.form();log_action("save_settings");with db_lock:conn=get_db();[conn.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))for k,v in f.items()];conn.commit();conn.close()
    return RedirectResponse("/settings",303)

@app.get("/logs",response_class=HTMLResponse)
def logs_page(u:str=Depends(auth_admin)):
    with db_lock:conn=get_db();logs=conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 50').fetchall();conn.close()
    rows=""
    for l in logs:rows+=f'<tr class="border-b border-dark-700 hover:bg-dark-700/50"><td class="py-3 px-4 text-gray-500 text-xs font-mono">{l["ts"]}</td><td class="py-3 px-4"><span class="px-2 py-1 bg-dark-900 border border-dark-600 rounded text-xs text-blue-400 font-mono">{l["action"]}</span></td><td class="py-3 px-4 text-sm text-gray-300">{l["details"]}</td></tr>'
    h=f'''<div class="max-w-4xl mx-auto"><h2 class="text-3xl font-bold mb-8">Activity Logs</h2><div class="bg-dark-800 rounded-2xl border border-dark-700 overflow-hidden shadow-xl"><table class="w-full text-left"><thead><tr class="bg-dark-900/50 border-b border-dark-700"><th class="py-4 px-4 font-medium text-gray-400 text-sm">Time</th><th class="py-4 px-4 font-medium text-gray-400 text-sm">Action</th><th class="py-4 px-4 font-medium text-gray-400 text-sm">Details</th></tr></thead><tbody>{rows}</tbody></table></div></div>'''
    return page("Logs",h,"logs")

def start_web_panel(host="0.0.0.0",port=8080,admin_key="admin123"):
    global ADMIN_PASS;ADMIN_PASS=admin_key;import uvicorn;uvicorn.run(app,host=host,port=port,log_level="warning")

if __name__=="__main__":start_web_panel()