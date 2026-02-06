import os
import requests
import base64
import math
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter, ImageEnhance

app = Flask(__name__)

# --- SETTINGS ---
CACHE_SECONDS = 300 # 5 minutes
DEFAULT_BG = "https://i.imgur.com/2aL8jE3.jpeg" # Fallback Chillax Landscape

# --- HELPERS ---

def fetch_image_b64(url, blur_radius=0, darken=0.0, resize_dims=None):
    """
    Downloads image, optionally resizes, blurs, and darkens it using Pillow (Python).
    Returns: "data:image/jpeg;base64,..." string.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            
            # 1. Convert
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 2. Resize (Optimization)
            if resize_dims:
                img = img.resize(resize_dims, Image.Resampling.LANCZOS)
            
            # 3. Blur (Frosted Effect)
            if blur_radius > 0:
                img = img.filter(ImageFilter.GaussianBlur(blur_radius))
            
            # 4. Darken (Tint)
            if darken > 0:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(1.0 - darken) # 1.0 = Original

            # 5. Output
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64_str}"
    except:
        return ""

def shorten(num):
    """1200 -> 1.2k"""
    try:
        n = float(num)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000: return f"{n/1_000:.1f}k"
        return str(int(n))
    except: return "0"

# --- MAIN ROUTE ---

@app.route('/stats')
def render_stats():
    # 1. QUERY PARAMS
    invite_code = request.args.get('invite')
    owner_id = request.args.get('owner')
    bg_url = request.args.get('bg') or DEFAULT_BG

    if not invite_code:
        return Response("Error: Add ?invite=YOUR_CODE to URL", status=400)

    # 2. DISCORD SERVER API (v10)
    server = {
        "valid": False, "name": "Server Not Found", "icon": "",
        "members": "---", "online": "---", "id": ""
    }
    
    try:
        r = requests.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true", timeout=4)
        if r.status_code == 200:
            d = r.json()
            guild = d.get('guild')
            if guild:
                server['valid'] = True
                server['name'] = guild.get('name', 'Discord Server')
                server['id'] = guild['id']
                server['members'] = shorten(d.get('approximate_member_count', 0))
                server['online'] = shorten(d.get('approximate_presence_count', 0))
                
                if guild.get('icon'):
                    # Fetch Icon (Keep sharp)
                    icon_url = f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png?size=128"
                    server['icon'] = fetch_image_b64(icon_url, resize_dims=(80,80))
        else:
            server['name'] = f"Invalid Invite ({r.status_code})"
    except Exception as e:
        server['name'] = "API Error"

    # 3. LANYARD API (Owner Status)
    owner = {
        "active": False, "name": "", "avatar": "", 
        "color": "#747f8d", "status_text": "Offline"
    }

    if owner_id:
        try:
            r = requests.get(f"https://api.lanyard.rest/v1/users/{owner_id}", timeout=3)
            d = r.json()
            if d.get('success'):
                data = d['data']
                discord = data['discord_user']
                
                owner['active'] = True
                owner['name'] = discord['username']
                
                # Status Color
                status_map = {'online':'#3ba55c','idle':'#faa61a','dnd':'#ed4245','offline':'#747f8d'}
                owner['color'] = status_map.get(data['discord_status'], '#747f8d')
                
                # Activity Text
                acts = data.get('activities', [])
                if acts:
                    # Logic to find "Playing" vs "Custom"
                    first_act = acts[0]
                    if first_act['type'] == 4: # Custom Status
                        owner['status_text'] = first_act.get('state', 'Custom Status')
                    elif first_act['type'] == 2: # Spotify
                         owner['status_text'] = f"Listening to {first_act.get('name')}"
                    else:
                        owner['status_text'] = f"Playing {first_act.get('name')}"
                else:
                    owner['status_text'] = data['discord_status'].capitalize()

                # Avatar
                if discord['avatar']:
                    # We crop circle via SVG mask later, just get raw square here
                    av_url = f"https://cdn.discordapp.com/avatars/{discord['id']}/{discord['avatar']}.png?size=64"
                    owner['avatar'] = fetch_image_b64(av_url, resize_dims=(60,60))
        except:
            pass # Fail silently (just don't show owner)

    # 4. IMAGE PROCESSING (The Magic for Glass Effect)
    # We blur the background image in Python so it works everywhere (Github/Discord)
    bg_b64 = fetch_image_b64(bg_url, blur_radius=3, darken=0.3, resize_dims=(500, 200))
    
    # 5. GENERATE SVG
    W, H = 450, 140
    
    # CSS Styles for Texts
    style = """
        <style>
            .base { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
            .h1 { font-weight: 800; font-size: 20px; fill: white; text-shadow: 0px 2px 4px rgba(0,0,0,0.5); }
            .h2 { font-weight: 700; font-size: 14px; fill: white; }
            .sub { font-weight: 500; font-size: 12px; fill: #d1d5db; }
            .stat_val { font-weight: 800; font-size: 14px; fill: #3ba55c; }
            .stat_lbl { font-weight: 600; font-size: 10px; fill: #b9bbbe; text-transform: uppercase; }
        </style>
    """

    svg = f"""
    <svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
        {style}
        <defs>
            <clipPath id="cardClip"><rect width="{W}" height="{H}" rx="12"/></clipPath>
            <clipPath id="circle"><circle cx="20" cy="20" r="20"/></clipPath>
            <linearGradient id="fade" x1="0" y1="0" x2="1" y2="0">
                 <stop offset="0.3" stop-color="rgba(0,0,0,0.8)"/>
                 <stop offset="1" stop-color="rgba(0,0,0,0.3)"/>
            </linearGradient>
        </defs>

        <!-- Main Card Body -->
        <g clip-path="url(#cardClip)">
            <!-- 1. Blurred Background Image -->
            <image x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice" href="{bg_b64}"/>
            
            <!-- 2. "Chillax" Sidebar Gradient Overlay -->
            <rect width="{W}" height="{H}" fill="url(#fade)"/>
            
            <!-- 3. SERVER INFO (Left Side) -->
            <!-- Server Icon -->
            <g transform="translate(20, 25)">
                <mask id="sqr"><rect x="0" y="0" width="60" height="60" rx="15" fill="white"/></mask>
                <image x="0" y="0" width="60" height="60" href="{server['icon']}" mask="url(#sqr)" />
                <rect x="0" y="0" width="60" height="60" rx="15" stroke="white" stroke-opacity="0.2" fill="none"/>
            </g>
            
            <!-- Text Info -->
            <text x="95" y="48" class="base h1">{server['name']}</text>
            
            <circle cx="100" cy="72" r="4" fill="#3ba55c"/>
            <text x="110" y="76" class="base sub"><tspan fill="#fff" font-weight="bold">{server['online']}</tspan> Online</text>
            
            <circle cx="170" cy="72" r="4" fill="#b9bbbe"/>
            <text x="180" y="76" class="base sub"><tspan fill="#fff" font-weight="bold">{server['members']}</tspan> Members</text>
        </g>
    """
    
    # 6. OPTIONAL: OWNER INFO (Floating Widget on Right)
    if owner['active']:
        svg += f"""
        <g transform="translate({W-160}, {H-50})">
             <!-- Translucent badge bg -->
             <rect x="0" y="0" width="150" height="40" rx="20" fill="black" fill-opacity="0.5"/>
             <rect x="0" y="0" width="150" height="40" rx="20" fill="none" stroke="white" stroke-opacity="0.1"/>
             
             <!-- Avatar -->
             <mask id="ownmask"><circle cx="20" cy="20" r="16" fill="white"/></mask>
             <image x="4" y="4" width="32" height="32" href="{owner['avatar']}" mask="url(#ownmask)"/>
             
             <!-- Status Dot -->
             <circle cx="30" cy="28" r="4" fill="{owner['color']}" stroke="#000" stroke-width="2"/>
             
             <!-- Name & Status -->
             <text x="45" y="16" class="base sub" font-size="9px">OWNER</text>
             <text x="45" y="29" class="base h2" font-size="12px">{owner['name']}</text>
        </g>
        """

    svg += "</svg>"

    resp = make_response(svg)
    resp.headers['Content-Type'] = 'image/svg+xml'
    # Short cache prevents stale status
    resp.headers['Cache-Control'] = f'max-age={CACHE_SECONDS}'
    return resp

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
