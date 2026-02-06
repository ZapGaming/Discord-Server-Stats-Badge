import os
import requests
import base64
import html
import time
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter, ImageEnhance

app = Flask(__name__)

# --- CONFIG ---
BOT_TOKEN = os.environ.get("DISCORD_TOKEN")

# Internal Caches
# Structure: { key: { "data": ..., "expires": timestamp } }
CACHE_SERVER = {}
CACHE_USER = {}
CACHE_IMG = {}

DEFAULT_BG = "https://i.imgur.com/2aL8jE3.jpeg"

# --- HELPERS ---

def get_headers():
    h = {
        "User-Agent": "DiscordBot (https://github.com/generic/app, 1.0)", 
        "Accept": "application/json"
    }
    if BOT_TOKEN:
        h["Authorization"] = f"Bot {BOT_TOKEN}"
    return h

def safe_str(txt):
    return html.escape(str(txt)) if txt else ""

def get_smart_timeout_image(url, width=100, blur=0, dim=0.0):
    """
    Safely fetches image. 
    Crucial fix: Returns Default BG if the URL is slow/blocked (like betterdiscord).
    """
    key = f"{url}-{width}-{blur}-{dim}"
    if key in CACHE_IMG:
        return CACHE_IMG[key]

    try:
        # STRICT TIMEOUT: 3 seconds. If bg takes longer, we skip it.
        # Verify=False helps with some bad SSL certs on random image hosts
        r = requests.get(url, timeout=3, headers={"User-Agent":"Mozilla/5.0"}) 
        
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert('RGB')
            
            # Resize
            ratio = img.height / img.width
            new_h = int(width * ratio)
            img = img.resize((width, new_h), Image.Resampling.LANCZOS)
            
            # Process
            if blur > 0: img = img.filter(ImageFilter.GaussianBlur(blur))
            if dim > 0:
                e = ImageEnhance.Brightness(img)
                img = e.enhance(1.0 - dim)

            buff = BytesIO()
            img.save(buff, format="JPEG", quality=85)
            b64 = f"data:image/jpeg;base64,{base64.b64encode(buff.getvalue()).decode('utf-8')}"
            
            res = {"data": b64, "w": width, "h": new_h}
            CACHE_IMG[key] = res
            return res
            
    except Exception as e:
        print(f"Skipping BG {url}: {e}")
        pass # Fallback below

    # Check if we were trying to fetch default, if so avoid infinite loop
    if url == DEFAULT_BG: return {"data": "", "w": width, "h": 100}
    
    # Fallback to internal logic
    return get_smart_timeout_image(DEFAULT_BG, width, blur, dim)

# --- API LOGIC (NO RETRY SLEEPING) ---

def get_cached_or_fetch(url, cache_dict, expiry=120, key=None):
    now = time.time()
    k = key or url
    
    # 1. Return Cache if fresh
    if k in cache_dict:
        item = cache_dict[k]
        if now < item['expires']:
            return item['payload']

    # 2. Try Fetch
    try:
        r = requests.get(url, headers=get_headers(), timeout=4) # MAX 4 sec
        
        if r.status_code == 200:
            data = r.json()
            # Cache it
            cache_dict[k] = {"payload": data, "expires": now + expiry}
            return data
            
        elif r.status_code == 429:
            # 3. IF RATE LIMITED, RETURN OLD DATA IF EXISTS
            if k in cache_dict:
                print(f"Rate limit hit for {k}, using stale cache.")
                return cache_dict[k]['payload']
            print(f"Rate limited hard on {k}, no cache.")
            return None
    except:
        # If timeout, return stale cache if exists
        if k in cache_dict: return cache_dict[k]['payload']
        return None

    return None

def process_staff_list(staff_str):
    """Parses id:role:color string."""
    cards = []
    if not staff_str: return cards
    
    for entry in staff_str.split(','):
        if not entry.strip(): continue
        
        parts = entry.strip().split(':')
        uid = parts[0]
        role = parts[1] if len(parts) > 1 else "Member"
        color = parts[2] if len(parts) > 2 else None
        
        user_obj = {
            "name": "User", "role": safe_str(role), 
            "color": color or "#747f8d", "avatar": ""
        }
        
        # 1. Try Lanyard
        lan_url = f"https://api.lanyard.rest/v1/users/{uid}"
        l_data = get_cached_or_fetch(lan_url, CACHE_USER, expiry=300) # 5 min cache for users
        
        fetched_discord_data = False
        
        if l_data and l_data.get('success'):
             data = l_data['data']
             du = data['discord_user']
             user_obj['name'] = safe_str(du['username'])
             fetched_discord_data = True
             
             if not color:
                 st = data.get('discord_status','offline')
                 cmap = {'online':'#3ba55c','idle':'#faa61a','dnd':'#ed4245','offline':'#747f8d'}
                 user_obj['color'] = cmap.get(st, '#747f8d')
             
             if du.get('avatar'):
                  ext = "gif" if du['avatar'].startswith("a_") else "png"
                  user_obj['avatar'] = f"https://cdn.discordapp.com/avatars/{uid}/{du['avatar']}.{ext}?size=64"

        # 2. If Lanyard failed, try Direct Discord
        if not fetched_discord_data:
             d_url = f"https://discord.com/api/v10/users/{uid}"
             d_data = get_cached_or_fetch(d_url, CACHE_USER, expiry=3600)
             if d_data:
                 user_obj['name'] = safe_str(d_data.get('username','User'))
                 if d_data.get('avatar'):
                     user_obj['avatar'] = f"https://cdn.discordapp.com/avatars/{uid}/{d_data['avatar']}.png?size=64"

        # Prepare Avatar for SVG (Download to Base64)
        if user_obj['avatar']:
            user_obj['avatar'] = get_smart_timeout_image(user_obj['avatar'], width=50)['data']

        cards.append(user_obj)
        
    return cards

# --- ROUTE ---

@app.route('/stats')
def render():
    invite = request.args.get('invite')
    bg_raw = request.args.get('bg')
    staff = request.args.get('staff')
    
    # Force default if using that specific bad URL or none
    if not bg_raw or "betterdiscord" in bg_raw:
        bg_url = DEFAULT_BG
    else:
        bg_url = bg_raw

    if not invite:
        return Response("Error: ?invite=CODE needed", status=400)

    # 1. BG Image
    bg = get_smart_timeout_image(bg_url, width=800, blur=0, dim=0.3)
    W, H = bg['w'], bg['h']

    # 2. Server Stats
    s = {"name": "Loading...", "onl": "0", "mem": "0", "icon": ""}
    
    api_url = f"https://discord.com/api/v10/invites/{invite}?with_counts=true"
    s_data = get_cached_or_fetch(api_url, CACHE_SERVER, expiry=60, key=invite) # 1 min cache for counts
    
    if s_data:
        guild = s_data.get('guild', {})
        s['name'] = safe_str(guild.get('name'))
        s['mem'] = f"{s_data.get('approximate_member_count', 0):,}"
        s['onl'] = f"{s_data.get('approximate_presence_count', 0):,}"
        if guild.get('icon'):
            u = f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png?size=128"
            s['icon'] = get_smart_timeout_image(u, width=80)['data']
    else:
        # Fallback if Rate Limited / API down
        s['name'] = "Server Info (Limited)"

    # 3. Staff
    staff_cards = process_staff_list(staff)

    # 4. SVG Construction
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, sans-serif"
    
    svg = f"""<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <clipPath id="rn"><rect width="80" height="80" rx="16"/></clipPath>
        <clipPath id="ci"><circle cx="20" cy="20" r="20"/></clipPath>
    </defs>
    
    <!-- BG -->
    <image href="{bg['data']}" width="{W}" height="{H}" preserveAspectRatio="none"/>
    
    <!-- HEADER -->
    <g transform="translate(40,40)">
        <rect width="400" height="110" rx="20" fill="black" fill-opacity="0.6"/>
        <rect width="400" height="110" rx="20" fill="none" stroke="white" stroke-opacity="0.1"/>
        
        <g transform="translate(15, 15)">
            <g clip-path="url(#rn)"><image href="{s['icon']}" width="80" height="80"/></g>
        </g>
        
        <text x="110" y="45" fill="white" font-family="{font}" font-weight="800" font-size="26">{s['name']}</text>
        
        <g transform="translate(110, 75)">
            <circle cx="6" cy="6" r="6" fill="#3ba55c"/>
            <text x="18" y="11" fill="#ddd" font-family="{font}" font-weight="600" font-size="14">{s['onl']} Online</text>
            <circle cx="120" cy="6" r="6" fill="#b9bbbe"/>
            <text x="132" y="11" fill="#ddd" font-family="{font}" font-weight="600" font-size="14">{s['mem']} Members</text>
        </g>
    </g>
    
    <!-- STAFF -->
    <g transform="translate(40, {H-80})">
    """
    
    off = 0
    for u in staff_cards:
        if not u['avatar']: continue
        svg += f"""
        <g transform="translate({off}, 0)">
            <rect width="200" height="50" rx="25" fill="black" fill-opacity="0.75"/>
            <rect width="200" height="50" rx="25" fill="none" stroke="{u['color']}" stroke-opacity="0.5"/>
            <g transform="translate(5, 5)">
                 <g clip-path="url(#ci)"><image href="{u['avatar']}" width="40" height="40"/></g>
                 <circle cx="20" cy="20" r="21" fill="none" stroke="{u['color']}" stroke-width="2"/>
            </g>
            <text x="55" y="20" fill="white" font-family="{font}" font-weight="700" font-size="13">{u['name'][:14]}</text>
            <text x="55" y="36" fill="{u['color']}" font-family="{font}" font-weight="800" font-size="9" letter-spacing="1">{u['role'][:18].upper()}</text>
        </g>
        """
        off += 210
        
    svg += "</g></svg>"

    r = make_response(svg)
    r.headers['Content-Type'] = 'image/svg+xml'
    r.headers['Cache-Control'] = 'max-age=120' # Tell GitHub to cache this for 2 mins
    return r

if __name__ == "__main__":
    # Local Dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
