import os
import requests
import base64
import time
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter, ImageEnhance

app = Flask(__name__)

# --- CONFIGURATION ---
# YOU MUST ADD THIS IN RENDER ENV VARS
BOT_TOKEN = os.environ.get("DISCORD_TOKEN") 

CACHE_TTL = 300 # 5 minutes cache
CACHE = {}

# --- HELPERS ---

def get_headers(use_token=False):
    headers = {"User-Agent": "ServerStats/1.0"}
    if use_token and BOT_TOKEN:
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    return headers

def fetch_and_process_image(url, blur=0, dim_opacity=0.0, target_width=800):
    """
    Downloads image, detects ratio, optionally blurs, returns Base64 + Dimensions
    """
    cache_key = f"img_{url}_{blur}_{target_width}"
    if cache_key in CACHE: return CACHE[cache_key]

    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert('RGB')
            
            # Calculate Aspect Ratio
            orig_w, orig_h = img.size
            ratio = orig_h / orig_w
            new_h = int(target_width * ratio)
            
            # Resize
            img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            
            # Blur
            if blur > 0:
                img = img.filter(ImageFilter.GaussianBlur(blur))
            
            # Darken/Dim
            if dim_opacity > 0:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(1.0 - dim_opacity)

            # Save
            buff = BytesIO()
            img.save(buff, format="JPEG", quality=90)
            b64 = f"data:image/jpeg;base64,{base64.b64encode(buff.getvalue()).decode('utf-8')}"
            
            result = {"b64": b64, "width": target_width, "height": new_h}
            CACHE[cache_key] = result
            return result
    except Exception as e:
        print(f"Img Error: {e}")
        # Fallback Placeholder
        return {"b64": "", "width": target_width, "height": 450} # Default 16:9-ish

def fetch_user_lanyard(user_id):
    """Get accurate online status from Lanyard."""
    try:
        r = requests.get(f"https://api.lanyard.rest/v1/users/{user_id}", timeout=2)
        d = r.json()
        if d['success']:
            return d['data']
    except:
        return None
    return None

def fetch_user_discord(user_id):
    """Fallback: fetch user profile info via Discord Bot API if Lanyard fails."""
    if not BOT_TOKEN: return None
    try:
        r = requests.get(f"https://discord.com/api/v10/users/{user_id}", headers=get_headers(True), timeout=3)
        return r.json() if r.status_code == 200 else None
    except:
        return None

# --- MAIN STATS ENGINE ---

@app.route('/stats')
def render_complex_card():
    # PARAMS
    invite_code = request.args.get('invite')
    bg_url = request.args.get('bg', 'https://i.imgur.com/2aL8jE3.jpeg') # Default Landscape
    
    # Staff Parser: ?staff=123:Owner,456:Dev,789:Mod
    staff_param = request.args.get('staff', '') 
    
    if not invite_code:
        return "Error: invite param required"

    # 1. PROCESS BACKGROUND (Determines SVG Dimensions)
    # We fix width at 800px for HD look, Height depends on image
    bg_data = fetch_and_process_image(bg_url, blur=8, dim_opacity=0.3, target_width=800)
    W, H = bg_data['width'], bg_data['height']

    # 2. FETCH SERVER DATA (Bot Auth Preferred)
    s_data = {"name": "Unknown", "mem": "0", "onl": "0", "icon": ""}
    
    # Try fetching invite
    try:
        r = requests.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true", headers=get_headers(), timeout=5)
        if r.status_code == 200:
            d = r.json()
            guild = d['guild']
            s_data['name'] = guild.get('name', 'Server')
            s_data['mem'] = f"{d.get('approximate_member_count', 0):,}" # 1,203 format
            s_data['onl'] = f"{d.get('approximate_presence_count', 0):,}"
            
            if guild.get('icon'):
                u = f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png?size=128"
                # Icon doesn't need blur
                s_data['icon'] = fetch_and_process_image(u, target_width=100)['b64']
    except:
        s_data['name'] = "API Error (Check Token)"

    # 3. PROCESS STAFF/EXTRA USERS
    staff_list = []
    if staff_param:
        entries = staff_param.split(',')
        for entry in entries:
            # Expected format: ID:Role (e.g. 7093..:Owner)
            if ":" in entry:
                uid, role = entry.split(':', 1)
            else:
                uid, role = entry, "Member"
            
            uid = uid.strip()
            
            # Fetch Info
            u_obj = {"name": "Unknown", "role": role, "color": "#747f8d", "avatar": ""}
            
            l_data = fetch_user_lanyard(uid)
            if l_data:
                # Use Lanyard Data
                discord = l_data['discord_user']
                u_obj['name'] = discord['username']
                
                status_map = {'online':'#3ba55c','idle':'#faa61a','dnd':'#ed4245','offline':'#747f8d'}
                u_obj['color'] = status_map.get(l_data['discord_status'], '#747f8d')
                
                if discord['avatar']:
                     u_obj['avatar'] = f"https://cdn.discordapp.com/avatars/{discord['id']}/{discord['avatar']}.png?size=64"
            else:
                # Fallback to simple Discord Bot lookup (no status)
                d_user = fetch_user_discord(uid)
                if d_user:
                    u_obj['name'] = d_user['username']
                    if d_user.get('avatar'):
                        u_obj['avatar'] = f"https://cdn.discordapp.com/avatars/{d_user['id']}/{d_user['avatar']}.png?size=64"

            # Convert avatar to B64 for SVG embedding
            if u_obj['avatar']:
                # Small cached avatar
                img_res = fetch_and_process_image(u_obj['avatar'], target_width=50)
                u_obj['avatar'] = img_res['b64']
            
            staff_list.append(u_obj)

    # 4. GENERATE COMPLEX SVG
    
    # Styles
    font_main = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    
    svg_content = f"""
    <svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <filter id="shadow" x="-50%" y="-50%" width="200%" height="200%">
                <feDropShadow dx="0" dy="4" stdDeviation="6" flood-opacity="0.5"/>
            </filter>
            <clipPath id="rnd"><rect width="80" height="80" rx="20"/></clipPath>
            <clipPath id="circle"><circle cx="25" cy="25" r="25"/></clipPath>
        </defs>

        <!-- FULL BG IMAGE -->
        <image href="{bg_data['b64']}" width="{W}" height="{H}" preserveAspectRatio="none" />
        
        <!-- Dark Gradient Overlay (Visibility) -->
        <rect width="{W}" height="{H}" fill="black" fill-opacity="0.4"/>

        <!-- --- SECTION 1: SERVER HEADER (Top Left) --- -->
        <g transform="translate(40, 40)">
             <!-- Frosted Card Backing -->
             <rect x="-10" y="-10" width="350" height="100" rx="15" fill="#000" fill-opacity="0.5" stroke="#fff" stroke-opacity="0.1"/>
             
             <!-- Icon -->
             <g clip-path="url(#rnd)">
                 <image href="{s_data['icon']}" width="80" height="80"/>
             </g>
             
             <!-- Text -->
             <text x="100" y="30" fill="white" font-family="{font_main}" font-weight="800" font-size="28">{s_data['name']}</text>
             
             <!-- Stats Row -->
             <g transform="translate(100, 60)">
                 <circle cx="8" cy="6" r="6" fill="#3ba55c"/>
                 <text x="22" y="11" fill="#ddd" font-family="{font_main}" font-size="16" font-weight="600">{s_data['onl']} Online</text>
                 
                 <circle cx="150" cy="6" r="6" fill="#b9bbbe"/>
                 <text x="164" y="11" fill="#ddd" font-family="{font_main}" font-size="16" font-weight="600">{s_data['mem']} Members</text>
             </g>
        </g>
        
        <!-- --- SECTION 2: STAFF / ROLES (Bottom Area) --- -->
        <g transform="translate(40, {H - 90})">
            <!-- Label -->
            <text x="0" y="-20" fill="white" font-family="{font_main}" font-size="12" font-weight="800" letter-spacing="2" opacity="0.8">SERVER TEAM</text>
    """
    
    # Loop to render staff badges horizontally
    x_off = 0
    for s in staff_list:
        if not s['avatar']: continue
        
        svg_content += f"""
        <g transform="translate({x_off}, 0)">
            <!-- Glass Pill -->
            <rect width="210" height="60" rx="30" fill="#000" fill-opacity="0.6" stroke="#fff" stroke-opacity="0.15"/>
            
            <!-- Avatar -->
            <g transform="translate(5, 5)">
                 <g clip-path="url(#circle)">
                    <image href="{s['avatar']}" width="50" height="50"/>
                 </g>
                 <!-- Status Dot Border -->
                 <circle cx="40" cy="40" r="8" fill="{s['color']}" stroke="#18181b" stroke-width="2"/>
            </g>
            
            <!-- Info -->
            <text x="65" y="25" fill="#fff" font-family="{font_main}" font-size="15" font-weight="700">{s['name']}</text>
            <text x="65" y="44" fill="{s['color']}" font-family="{font_main}" font-size="11" font-weight="700" text-transform="uppercase">{s['role']}</text>
        </g>
        """
        x_off += 220 # Gap between cards

    svg_content += """
        </g>
    </svg>
    """

    resp = make_response(svg_content)
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['Cache-Control'] = 'no-cache, max-age=300'
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
