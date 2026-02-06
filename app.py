import os
import requests
import base64
import html 
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter, ImageEnhance

app = Flask(__name__)

# --- ENV ---
# Ensure you add DISCORD_TOKEN to Render Environment Variables
BOT_TOKEN = os.environ.get("DISCORD_TOKEN") 

CACHE = {}

# --- HELPERS ---

def get_headers(use_token=False):
    headers = {"User-Agent": "ServerStats/1.0"}
    if use_token and BOT_TOKEN:
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    return headers

def safe_txt(text):
    """Escapes characters like <, >, & to prevent XML errors."""
    return html.escape(str(text)) if text else ""

def fetch_and_process_image(url, blur=0, dim_opacity=0.0, target_width=800):
    """Downloads, resizes, blurs, and returns B64."""
    # Simple In-Memory Cache to prevent repeated processing
    cache_key = f"img_{url}_{blur}_{dim_opacity}_{target_width}"
    if cache_key in CACHE: return CACHE[cache_key]

    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert('RGB')
            
            # 1. Calc Aspect Ratio
            w, h = img.size
            ratio = h / w
            new_h = int(target_width * ratio)
            
            # 2. Resize
            img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            
            # 3. Blur
            if blur > 0:
                img = img.filter(ImageFilter.GaussianBlur(blur))
            
            # 4. Dim (Dark Overlay baked in)
            if dim_opacity > 0:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(1.0 - dim_opacity)

            buff = BytesIO()
            img.save(buff, format="JPEG", quality=90)
            b64 = f"data:image/jpeg;base64,{base64.b64encode(buff.getvalue()).decode('utf-8')}"
            
            res = {"b64": b64, "w": target_width, "h": new_h}
            CACHE[cache_key] = res
            return res
    except:
        pass
    
    # Return placeholder if failed
    return {"b64": "", "w": target_width, "h": 400}

# --- DATA FETCHERS ---

def fetch_lanyard(user_id):
    try:
        r = requests.get(f"https://api.lanyard.rest/v1/users/{user_id}", timeout=2)
        return r.json()['data'] if r.status_code == 200 and r.json()['success'] else None
    except: return None

def fetch_discord_user(user_id):
    if not BOT_TOKEN: return None
    try:
        r = requests.get(f"https://discord.com/api/v10/users/{user_id}", headers=get_headers(True), timeout=3)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- MAIN ROUTE ---

@app.route('/stats')
def render_stats():
    # Params
    invite_code = request.args.get('invite')
    bg_url = request.args.get('bg', 'https://i.imgur.com/2aL8jE3.jpeg') 
    staff_param = request.args.get('staff', '') # Format: ID:Role,ID:Role

    if not invite_code:
        return Response("Error: Missing ?invite=CODE", status=400)

    # 1. Process Background (Get Dimensions)
    # Using target_width 800 for high quality on retina
    bg_data = fetch_and_process_image(bg_url, blur=0, dim_opacity=0.3, target_width=800)
    W, H = bg_data['w'], bg_data['h']
    
    # 2. Fetch Server Info (With Token)
    s_data = {"name": "Server Error", "mem": "0", "onl": "0", "icon": ""}
    
    try:
        r = requests.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true", headers=get_headers(use_token=True), timeout=5)
        d = r.json()
        
        if r.status_code == 200:
            g = d.get('guild')
            s_data['name'] = safe_txt(g.get('name'))
            s_data['mem'] = f"{d.get('approximate_member_count', 0):,}"
            s_data['onl'] = f"{d.get('approximate_presence_count', 0):,}"
            if g.get('icon'):
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=128"
                # Resize icon small for performance
                s_data['icon'] = fetch_and_process_image(icon_url, target_width=80)['b64']
        elif r.status_code == 429:
             s_data['name'] = "Rate Limited"
        else:
             s_data['name'] = "Invalid Invite"

    except Exception as e:
        print(e)

    # 3. Process Staff / Roles
    staff_cards = []
    if staff_param:
        for item in staff_param.split(','):
            # Safe parse "id:role" or just "id"
            parts = item.strip().split(':')
            uid = parts[0]
            role = parts[1] if len(parts) > 1 else "Staff"
            
            # Defaults
            user = {"name": "Unknown", "role": safe_txt(role), "color": "#747f8d", "avatar": ""}
            
            # Try Lanyard first
            lany = fetch_lanyard(uid)
            if lany:
                duser = lany['discord_user']
                user['name'] = safe_txt(duser['username'])
                
                status_map = {'online':'#3ba55c','idle':'#faa61a','dnd':'#ed4245','offline':'#747f8d'}
                user['color'] = status_map.get(lany['discord_status'], '#747f8d')
                
                if duser['avatar']:
                     url = f"https://cdn.discordapp.com/avatars/{duser['id']}/{duser['avatar']}.png?size=64"
                     user['avatar'] = fetch_and_process_image(url, target_width=64)['b64']
            else:
                # Fallback to Discord API
                duser = fetch_discord_user(uid)
                if duser:
                    user['name'] = safe_txt(duser['username'])
                    if duser.get('avatar'):
                        url = f"https://cdn.discordapp.com/avatars/{duser['id']}/{duser['avatar']}.png?size=64"
                        user['avatar'] = fetch_and_process_image(url, target_width=64)['b64']

            staff_cards.append(user)

    # 4. Construct SVG
    font = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    
    svg = f"""<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <clipPath id="rnd"><rect width="80" height="80" rx="18"/></clipPath>
        <clipPath id="circ"><circle cx="24" cy="24" r="24"/></clipPath>
    </defs>

    <!-- Background -->
    <image href="{bg_data['b64']}" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice" />
    <rect width="{W}" height="{H}" fill="black" fill-opacity="0.2"/>

    <!-- SECTION 1: SERVER INFO (Top Left) -->
    <g transform="translate(40, 40)">
        <!-- Blur Backdrop -->
        <rect x="-15" y="-15" width="420" height="110" rx="20" fill="black" fill-opacity="0.6"/>
        <rect x="-15" y="-15" width="420" height="110" rx="20" fill="none" stroke="white" stroke-opacity="0.1"/>

        <!-- Icon -->
        <g clip-path="url(#rnd)">
            <image href="{s_data['icon']}" width="80" height="80"/>
        </g>
        
        <!-- Text Details -->
        <text x="100" y="32" fill="white" font-family="{font}" font-weight="800" font-size="24">{s_data['name']}</text>
        
        <g transform="translate(100, 60)">
             <circle cx="8" cy="8" r="5" fill="#3ba55c"/>
             <text x="22" y="13" fill="#cfd0d1" font-family="{font}" font-weight="600" font-size="14">{s_data['onl']} Online</text>
             
             <circle cx="140" cy="8" r="5" fill="#b9bbbe"/>
             <text x="154" y="13" fill="#cfd0d1" font-family="{font}" font-weight="600" font-size="14">{s_data['mem']} Members</text>
        </g>
    </g>

    <!-- SECTION 2: STAFF LIST (Bottom Left) -->
    <g transform="translate(40, {H - 90})">
        <!-- Optional Label -->
        <text x="5" y="-15" fill="white" font-family="{font}" font-weight="700" font-size="10" opacity="0.7" letter-spacing="1">TEAM STATUS</text>
    """
    
    # Render Staff Cards
    offset_x = 0
    for s in staff_cards:
        if not s['avatar']: continue
        
        svg += f"""
        <g transform="translate({offset_x}, 0)">
            <rect width="200" height="54" rx="27" fill="black" fill-opacity="0.7"/>
            <rect width="200" height="54" rx="27" fill="none" stroke="white" stroke-opacity="0.1"/>
            
            <g transform="translate(3, 3)">
                <g clip-path="url(#circ)">
                    <image href="{s['avatar']}" width="48" height="48"/>
                </g>
                <circle cx="38" cy="38" r="7" fill="{s['color']}" stroke="#202225" stroke-width="2"/>
            </g>
            
            <text x="60" y="22" fill="white" font-family="{font}" font-weight="700" font-size="14">{s['name']}</text>
            <text x="60" y="39" fill="{s['color']}" font-family="{font}" font-weight="700" font-size="10" text-transform="uppercase" letter-spacing="0.5">{s['role']}</text>
        </g>
        """
        offset_x += 210

    svg += """
    </g>
    </svg>
    """
    
    resp = make_response(svg)
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['Cache-Control'] = 'max-age=120'
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
