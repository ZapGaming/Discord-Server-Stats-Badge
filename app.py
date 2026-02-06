import os
import requests
import base64
from io import BytesIO
from flask import Flask, Response, request, make_response
from PIL import Image, ImageFilter # For handling the BG image size

app = Flask(__name__)

# --- CONFIG ---
# The generic Chillax-style background (Purple Mountains) if none is provided
DEFAULT_BG = "https://i.imgur.com/2aL8jE3.jpeg" # A reliable fallback link for the style 

def fetch_as_base64(url, resize=None, blur=False):
    """
    Downloads image, optimizes size (crucial for GitHub), 
    and returns Base64 string.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            
            # Convert to RGB (in case of PNG alpha issues)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize if requested (W, H)
            if resize:
                img = img.resize(resize, Image.Resampling.LANCZOS)
            
            # Buffer for output
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=80) # JPEG is lighter than PNG for backgrounds
            
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        print(f"Image Error ({url}): {e}")
        return ""

def fetch_png_base64(url):
    """Specific fetcher for Icons/Avatars (preserves transparency)."""
    try:
        r = requests.get(url, timeout=3)
        encoded = base64.b64encode(r.content).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except:
        return ""

def number_fmt(num):
    try:
        n = float(num)
        if n >= 1000000: return f"{n/1000000:.1f}M"
        if n >= 1000: return f"{n/1000:.1f}k"
        return str(int(n))
    except: return "0"

@app.route('/stats')
def render_stats():
    # 1. PARAMS
    invite_code = request.args.get('invite') or request.args.get('id')
    owner_id = request.args.get('owner')
    
    # Custom Background: allow user to override the chillax bg
    bg_url = request.args.get('bg') or DEFAULT_BG 
    
    if not invite_code:
        return Response("Error: Provide ?invite=CODE", status=400)

    # 2. DISCORD DATA (Invite API)
    discord_api = f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true"
    svr = {"name": "Server", "mem": "0", "onl": "0", "icon": ""}
    
    try:
        r = requests.get(discord_api, timeout=5)
        d = r.json()
        if 'guild' in d:
            g = d['guild']
            svr['name'] = g.get('name', '')
            svr['mem'] = d.get('approximate_member_count', 0)
            svr['onl'] = d.get('approximate_presence_count', 0)
            if g.get('icon'):
                svr['icon'] = fetch_png_base64(f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=64")
    except:
        pass

    # 3. OWNER DATA (Lanyard API)
    usr = {"active": False, "ava": "", "stat_col": "#747f8d", "act_text": "Chilling", "name": ""}
    if owner_id:
        try:
            r = requests.get(f"https://api.lanyard.rest/v1/users/{owner_id}", timeout=4)
            d = r.json()
            if d.get('success'):
                usr['active'] = True
                data = d['data']
                
                # Info
                usr['name'] = data['discord_user']['username']
                
                # Avatar
                u_id = data['discord_user']['id']
                u_av = data['discord_user']['avatar']
                if u_av:
                    usr['ava'] = fetch_png_base64(f"https://cdn.discordapp.com/avatars/{u_id}/{u_av}.png?size=64")
                
                # Status Color
                status = data['discord_status']
                if status == 'online': usr['stat_col'] = "#3ba55c"
                elif status == 'idle': usr['stat_col'] = "#faa61a"
                elif status == 'dnd': usr['stat_col'] = "#ed4245"
                
                # Rich Presence Logic
                if data['activities']:
                    act = data['activities'][0]
                    # Logic: "Playing X" or "Listening to X"
                    if act['type'] == 2: 
                        usr['act_text'] = f"Listening to {act.get('name', 'Spotify')}"
                    elif act['type'] == 0:
                        usr['act_text'] = f"Playing {act.get('name', 'Game')}"
                    elif act['type'] == 4:
                        usr['act_text'] = act.get('state', 'Custom Status')
        except:
            pass

    # 4. PREPARE ASSETS
    # Background: Resize to ~600x200 to save bandwidth/load time
    bg_b64 = fetch_as_base64(bg_url, resize=(600, 250))
    
    W, H = 400, 140
    
    # 5. RENDER SVG
    svg = f"""
    <svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <!-- Drop Shadow for floating feel -->
            <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur in="SourceAlpha" stdDeviation="4"/>
                <feOffset dx="0" dy="4" result="offsetblur"/>
                <feComponentTransfer>
                    <feFuncA type="linear" slope="0.5"/> <!-- Shadow Opacity -->
                </feComponentTransfer>
                <feMerge> 
                    <feMergeNode/>
                    <feMergeNode in="SourceGraphic"/> 
                </feMerge>
            </filter>
            
            <!-- Circular Clips -->
            <clipPath id="circle"><circle cx="20" cy="20" r="20"/></clipPath>
        </defs>

        <style>
            .txt {{ font-family: 'Segoe UI', sans-serif; fill: white; }}
            .sub {{ font-family: 'Segoe UI', sans-serif; fill: #d1d5db; font-size: 11px; }}
            .bold {{ font-weight: 700; }}
            .stat {{ font-weight: 800; font-size: 13px; }}
        </style>

        <!-- FLOATING CARD CONTAINER -->
        <g filter="url(#shadow)" transform="translate(10,10)">
            
            <!-- 1. Background Image (Masked to rounded rect) -->
            <mask id="cardMask">
                <rect width="{W-20}" height="{H-20}" rx="12" fill="white"/>
            </mask>
            <image href="{bg_b64}" width="{W-20}" height="{H-20}" preserveAspectRatio="none" mask="url(#cardMask)" />

            <!-- 2. "Frosted Glass" Overlay -->
            <!-- We use a black rect with low opacity to dim the BG, allowing text to pop (Chillax style) -->
            <rect width="{W-20}" height="{H-20}" rx="12" fill="#000000" fill-opacity="0.6"/>
            
            <!-- Optional: Thin border for glass edge -->
            <rect width="{W-20}" height="{H-20}" rx="12" fill="none" stroke="#ffffff" stroke-opacity="0.2" stroke-width="1"/>

            <!-- CONTENT GRID -->
            
            <!-- Server Icon -->
            <image href="{svr['icon']}" x="20" y="20" width="50" height="50" style="clip-path: circle(25px at 25px 25px);"/>
            
            <!-- Server Name -->
            <text x="82" y="38" class="txt bold" font-size="16">{svr['name']}</text>
            
            <!-- Server Stats -->
            <circle cx="88" cy="58" r="4" fill="#3ba55c"/>
            <text x="98" y="62" class="txt sub">{number_fmt(svr['onl'])} Online</text>
            
            <circle cx="160" cy="58" r="4" fill="#b9bbbe"/>
            <text x="170" y="62" class="txt sub">{number_fmt(svr['mem'])} Members</text>

            <!-- DIVIDER LINE -->
            <line x1="20" y1="85" x2="{W-40}" y2="85" stroke="white" stroke-opacity="0.15"/>
    """

    # OWNER SECTION (If found)
    if usr['active']:
        svg += f"""
            <g transform="translate(20, 95)">
                <!-- Owner Avatar -->
                <image href="{usr['ava']}" width="24" height="24" style="clip-path: circle(12px at 12px 12px);"/>
                
                <!-- Status Dot -->
                <circle cx="20" cy="20" r="4" fill="{usr['stat_col']}" stroke="#202225" stroke-width="1"/>
                
                <!-- Texts -->
                <text x="35" y="11" class="txt bold" font-size="11">{usr['name']}</text>
                <text x="35" y="23" class="sub" font-style="italic">{usr['act_text']}</text>

                <!-- Label (Far Right) -->
                <text x="{W-70}" y="17" class="txt" font-size="10" font-weight="900" opacity="0.5">OWNER</text>
            </g>
        """
    else:
        # Fallback text if no owner ID provided
        svg += f"""
            <text x="20" y="108" class="txt sub" opacity="0.7">Server Statistics Widget</text>
        """

    svg += """
        </g> <!-- End Floating Group -->
    </svg>
    """

    resp = make_response(svg)
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['Cache-Control'] = 'no-cache, max-age=300'
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
