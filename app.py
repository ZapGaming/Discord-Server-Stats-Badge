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
    """Escapes characters like <, >, &, " to prevent XML errors."""
    if not text: return ""
    return html.escape(str(text))

def fetch_and_process_image(url, blur=0, dim_opacity=0.0, target_width=800):
    cache_key = f"img_{url}_{blur}_{dim_opacity}_{target_width}"
    if cache_key in CACHE: return CACHE[cache_key]

    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert('RGB')
            
            w, h = img.size
            ratio = h / w
            new_h = int(target_width * ratio)
            
            img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            
            if blur > 0:
                img = img.filter(ImageFilter.GaussianBlur(blur))
            
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
    
    return {"b64": "", "w": target_width, "h": 400}

# --- FETCH DATA ---

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
    invite_code = request.args.get('invite')
    bg_url = request.args.get('bg', 'https://i.imgur.com/2aL8jE3.jpeg') 
    staff_param = request.args.get('staff', '') 

    if not invite_code:
        return Response("Error: Missing ?invite=CODE", status=400)

    # 1. Background
    bg_data = fetch_and_process_image(bg_url, blur=0, dim_opacity=0.3, target_width=800)
    W, H = bg_data['w'], bg_data['h']
    
    # 2. Server Data
    s_data = {"name": "Server Error", "mem": "0", "onl": "0", "icon": ""}
    
    try:
        # Tries to get data; if RateLimited (429), it returns "Rate Limited" text
        r = requests.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true", headers=get_headers(use_token=True), timeout=5)
        
        if r.status_code == 200:
            d = r.json()
            g = d.get('guild', {})
            s_data['name'] = safe_txt(g.get('name', 'Server'))
            s_data['mem'] = f"{d.get('approximate_member_count', 0):,}"
            s_data['onl'] = f"{d.get('approximate_presence_count', 0):,}"
            
            if g.get('icon'):
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=128"
                s_data['icon'] = fetch_and_process_image(icon_url, target_width=80)['b64']
        else:
            s_data['name'] = f"Invalid ({r.status_code})"

    except:
        s_data['name'] = "API Error"

    # 3. Staff Logic
    staff_cards = []
    if staff_param:
        for item in staff_param.split(','):
            if not item.strip(): continue
            parts = item.strip().split(':')
            uid = parts[0]
            role = parts[1] if len(parts) > 1 else "Staff"
            
            u_obj = {"name": "Unknown", "role": safe_txt(role), "color": "#747f8d", "avatar": ""}
            
            lany = fetch_lanyard(uid)
            if lany:
                duser = lany.get('discord_user')
                if duser:
                    u_obj['name'] = safe_txt(duser['username'])
                    # Check Lanyard Avatar
                    if duser['avatar']:
                        url = f"https://cdn.discordapp.com/avatars/{duser['id']}/{duser['avatar']}.png?size=64"
                        u_obj['avatar'] = fetch_and_process_image(url, target_width=64)['b64']
                    
                    status_map = {'online':'#3ba55c','idle':'#faa61a','dnd':'#ed4245','offline':'#747f8d'}
                    u_obj['color'] = status_map.get(lany.get('discord_status'), '#747f8d')
            else:
                duser = fetch_discord_user(uid)
                if duser:
                    u_obj['name'] = safe_txt(duser['username'])
                    if duser.get('avatar'):
                         url = f"https://cdn.discordapp.com/avatars/{duser['id']}/{duser['avatar']}.png?size=64"
                         u_obj['avatar'] = fetch_and_process_image(url, target_width=64)['b64']

            staff_cards.append(u_obj)

    # 4. Construct SVG
    # ERROR FIX: Switched from "Segoe UI" to 'Segoe UI' (Single quotes) to not break HTML attribute
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    
    # Header logic
    svg = f"""<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <defs>
        <clipPath id="rnd"><rect width="80" height="80" rx="18"/></clipPath>
        <clipPath id="circ"><circle cx="24" cy="24" r="24"/></clipPath>
    </defs>

    <!-- BG -->
    <image href="{bg_data['b64']}" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice" />
    <rect width="{W}" height="{H}" fill="black" fill-opacity="0.2"/>

    <!-- SECTION 1: SERVER INFO -->
    <g transform="translate(40, 40)">
        <rect x="-15" y="-15" width="420" height="110" rx="20" fill="black" fill-opacity="0.6"/>
        <rect x="-15" y="-15" width="420" height="110" rx="20" fill="none" stroke="white" stroke-opacity="0.1"/>

        <g clip-path="url(#rnd)">
            <image href="{s_data['icon']}" width="80" height="80"/>
        </g>
        
        <text x="100" y="32" fill="white" font-family="{font}" font-weight="800" font-size="24">{s_data['name']}</text>
        
        <g transform="translate(100, 60)">
             <circle cx="8" cy="8" r="5" fill="#3ba55c"/>
             <text x="22" y="13" fill="#cfd0d1" font-family="{font}" font-weight="600" font-size="14">{s_data['onl']} Online</text>
             
             <circle cx="140" cy="8" r="5" fill="#b9bbbe"/>
             <text x="154" y="13" fill="#cfd0d1" font-family="{font}" font-weight="600" font-size="14">{s_data['mem']} Members</text>
        </g>
    </g>

    <!-- SECTION 2: STAFF LIST -->
    <g transform="translate(40, {H - 90})">
    """

    if staff_cards:
        svg += f"""<text x="5" y="-15" fill="white" font-family="{font}" font-weight="700" font-size="10" opacity="0.7" letter-spacing="1">TEAM STATUS</text>"""

    x_offset = 0
    for s in staff_cards:
        if not s['avatar']: continue
        
        svg += f"""
        <g transform="translate({x_offset}, 0)">
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
        x_offset += 210

    svg += """</g></svg>"""
    
    resp = make_response(svg)
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['Cache-Control'] = 'no-cache, max-age=120'
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
