import os
import requests
import base64
import html
import time
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter, ImageEnhance
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# --- 1. CONFIGURATION ---
BOT_TOKEN = os.environ.get("DISCORD_TOKEN")
CACHE_DURATION = 120  # Seconds to cache data (Keep Discord happy)

# Internal RAM Cache
CACHE = {} 
IMG_CACHE = {}

# --- 2. THE BOT NETWORK ENGINE ---

# Setup a robust session with Retries to handle 429s automatically
session = requests.Session()

# Add logic to automatically wait and retry if Discord is busy
retry_strategy = Retry(
    total=3,
    backoff_factor=1,  # Wait 1s, then 2s, then 4s
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

def get_discord_headers():
    """Forces all requests to appear as the Bot, not the shared server IP."""
    headers = {
        "User-Agent": "DiscordBot (https://github.com/your-repo, 1.0)",
        "Content-Type": "application/json"
    }
    # This is the Key: Routes traffic via Bot Identity
    if BOT_TOKEN:
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    return headers

def safe(text):
    """Prevents XML breakage."""
    return html.escape(str(text)) if text else ""

# --- 3. ADVANCED IMAGE PROCESSING ---

def fetch_image_asset(url, width=100, height=None, blur=0, dim=0.0):
    """
    Downloads, resizes, optimizes, blurs, and caches images.
    """
    # 1. Check Cache
    key = f"{url}-{width}-{blur}-{dim}"
    if key in IMG_CACHE: return IMG_CACHE[key]

    try:
        # Use our session with headers (avoids blocking on image domains)
        r = session.get(url, timeout=5)
        
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert('RGB')

            # Smart Resize
            if not height:
                ratio = img.height / img.width
                height = int(width * ratio)
            
            img = img.resize((width, height), Image.Resampling.LANCZOS)

            # Apply Effects
            if blur > 0: img = img.filter(ImageFilter.GaussianBlur(blur))
            if dim > 0:
                e = ImageEnhance.Brightness(img)
                img = e.enhance(1.0 - dim)

            # Export
            buff = BytesIO()
            img.save(buff, format="JPEG", quality=90)
            b64 = f"data:image/jpeg;base64,{base64.b64encode(buff.getvalue()).decode('utf-8')}"
            
            # Save to Cache
            IMG_CACHE[key] = {"data": b64, "w": width, "h": height}
            return IMG_CACHE[key]
    except Exception as e:
        print(f"Img Error: {e}")

    # Fallback Placeholder
    return {"data": "", "w": width, "h": height or 100}

# --- 4. DATA LOGIC ---

def fetch_user_data(uid, override_role=None, override_color=None):
    """Combines Lanyard (Real Status) + Discord API (Profile)"""
    
    # Defaults
    user = {
        "name": "User", 
        "role": override_role or "Member", 
        "color": override_color or "#747f8d", 
        "avatar": "",
        "found": False
    }

    # A. Try Lanyard (For Status Color)
    try:
        r = session.get(f"https://api.lanyard.rest/v1/users/{uid}", timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data['success']:
                lanyard = data['data']
                discord = lanyard['discord_user']
                
                user['found'] = True
                user['name'] = discord['username']
                
                # Dynamic Status Color (unless overridden)
                if not override_color:
                    status = lanyard['discord_status']
                    colors = {'online': '#3ba55c', 'idle': '#faa61a', 'dnd': '#ed4245', 'offline': '#747f8d'}
                    user['color'] = colors.get(status, '#747f8d')

                # Avatar
                if discord['avatar']:
                     ext = "gif" if discord['avatar'].startswith("a_") else "png"
                     user['avatar'] = f"https://cdn.discordapp.com/avatars/{uid}/{discord['avatar']}.{ext}?size=64"
    except: pass

    # B. Fallback to Bot API (If Lanyard fails)
    if not user['found'] and BOT_TOKEN:
        try:
            r = session.get(f"https://discord.com/api/v10/users/{uid}", headers=get_headers(), timeout=3)
            if r.status_code == 200:
                d = r.json()
                user['name'] = d['username']
                if d.get('avatar'):
                    user['avatar'] = f"https://cdn.discordapp.com/avatars/{uid}/{d['avatar']}.png?size=64"
        except: pass

    return user

# --- 5. MAIN ROUTE ---

@app.route('/stats')
def render_stats():
    # INPUTS
    invite_code = request.args.get('invite')
    bg_url = request.args.get('bg') or "https://i.imgur.com/2aL8jE3.jpeg" # Default Chillax
    staff_string = request.args.get('staff', '') 
    
    if not invite_code:
        return Response("Error: Missing ?invite=CODE", status=400)

    # 1. PROCESS BG
    bg_asset = fetch_image_asset(bg_url, width=900, blur=0, dim=0.4)
    W, H = bg_asset['w'], bg_asset['h']

    # 2. FETCH SERVER
    s = {"name": "Server Loading", "onl": "0", "mem": "0", "icon": ""}
    
    try:
        # We explicitly use the BOT session here to route traffic
        url = f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true"
        r = session.get(url, headers=get_discord_headers(), timeout=5)
        
        if r.status_code == 200:
            d = r.json()
            g = d.get('guild')
            
            s['name'] = safe(g.get('name'))
            s['mem'] = f"{d.get('approximate_member_count', 0):,}"
            s['onl'] = f"{d.get('approximate_presence_count', 0):,}"
            
            if g.get('icon'):
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=128"
                # Process Icon
                s['icon'] = fetch_image_asset(icon_url, width=100)['data']
                
        elif r.status_code == 429:
            s['name'] = "Rate Limited (Wait)"
            print("Server is 429ing even with Bot Token.")
        else:
            s['name'] = f"Invalid Invite ({r.status_code})"

    except Exception as e:
        print(f"Server Error: {e}")
        s['name'] = "Connection Error"

    # 3. PROCESS STAFF ROLES
    # Format: id:Role:Color, id:Role
    staff_cards = []
    if staff_string:
        entries = staff_string.split(',')
        for entry in entries:
            parts = entry.strip().split(':')
            uid = parts[0]
            role = parts[1] if len(parts) > 1 else "Staff"
            color = parts[2] if len(parts) > 2 else None # Optional custom color override
            
            # Fetch
            u_data = fetch_user_data(uid, override_role=role, override_color=color)
            
            # Optimize Avatar for SVG
            if u_data['avatar']:
                u_data['avatar'] = fetch_image_asset(u_data['avatar'], width=64)['data']
            
            staff_cards.append(u_data)

    # 4. DRAW SVG (Complex Glass UI)
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    
    # Calculate Dynamic Height (Base + Staff Rows)
    # But for a banner we usually keep fixed or aspect. Let's trust the BG.
    
    svg = f"""
    <svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <defs>
        <clipPath id="c_icon"><rect width="80" height="80" rx="16"/></clipPath>
        <clipPath id="c_ava"><circle cx="20" cy="20" r="20"/></clipPath>
        <linearGradient id="grad_pill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#fff" stop-opacity="0.15"/>
            <stop offset="100%" stop-color="#fff" stop-opacity="0.05"/>
        </linearGradient>
    </defs>

    <!-- Background -->
    <image href="{bg_asset['data']}" width="{W}" height="{H}" />
    
    <!-- MAIN SERVER CARD (Floating Top Left) -->
    <g transform="translate(40, 40)">
        <!-- Frosted Glass Backing -->
        <rect width="450" height="120" rx="20" fill="#000" fill-opacity="0.65"/>
        <rect width="450" height="120" rx="20" fill="url(#grad_pill)" stroke="#fff" stroke-opacity="0.2"/>

        <!-- Server Icon -->
        <g transform="translate(20, 20)">
            <g clip-path="url(#c_icon)">
                <image href="{s['icon']}" width="80" height="80" preserveAspectRatio="xMidYMid slice"/>
            </g>
            <rect width="80" height="80" rx="16" fill="none" stroke="#fff" stroke-opacity="0.2"/>
        </g>
        
        <!-- Texts -->
        <text x="120" y="55" fill="#fff" font-family="{font}" font-weight="800" font-size="28" style="text-shadow: 0 2px 4px rgba(0,0,0,0.5)">{s['name']}</text>
        
        <!-- Live Counters -->
        <g transform="translate(120, 85)">
             <circle cx="6" cy="6" r="6" fill="#3ba55c"/>
             <text x="18" y="11" fill="#eee" font-family="{font}" font-weight="600" font-size="16">{s['onl']} Online</text>
             
             <circle cx="150" cy="6" r="6" fill="#b9bbbe"/>
             <text x="162" y="11" fill="#eee" font-family="{font}" font-weight="600" font-size="16">{s['mem']} Members</text>
        </g>
    </g>

    <!-- STAFF SECTION (Bottom Bar) -->
    <g transform="translate(40, {H - 90})">
    """
    
    # Label
    if staff_cards:
        svg += f"""<text x="0" y="-15" fill="#fff" font-family="{font}" font-weight="800" font-size="12" opacity="0.8" letter-spacing="2">KEY ROLES</text>"""

    offset_x = 0
    for u in staff_cards:
        if not u['avatar']: continue
        
        # Ensure role isn't too long
        d_role = u['role'][:20].upper()
        d_name = u['name'][:16]
        
        svg += f"""
        <g transform="translate({offset_x}, 0)">
            <!-- Pill Card -->
            <rect width="210" height="60" rx="30" fill="#000" fill-opacity="0.75" />
            <rect width="210" height="60" rx="30" fill="none" stroke="{u['color']}" stroke-opacity="0.4" stroke-width="1.5"/>
            
            <!-- Avatar Circle -->
            <g transform="translate(10, 10)">
                 <g clip-path="url(#c_ava)">
                    <image href="{u['avatar']}" width="40" height="40"/>
                 </g>
                 <!-- Status Indicator Border -->
                 <circle cx="20" cy="20" r="21" fill="none" stroke="{u['color']}" stroke-width="2"/>
            </g>
            
            <!-- Name / Role -->
            <text x="60" y="27" fill="#fff" font-family="{font}" font-weight="700" font-size="14">{d_name}</text>
            <text x="60" y="45" fill="{u['color']}" font-family="{font}" font-weight="800" font-size="10" letter-spacing="1">{d_role}</text>
        </g>
        """
        offset_x += 225

    svg += "</g></svg>"

    resp = make_response(svg)
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['Cache-Control'] = f'max-age={CACHE_DURATION}'
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
