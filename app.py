import os
import requests
import base64
from flask import Flask, Response, request, make_response

app = Flask(__name__)

# --- HELPERS ---

def sanitize_xml(text):
    """Escapes special characters for XML/SVG."""
    if not text: return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_base64_image(url):
    """Downloads an image and converts it to base64 for embedding in SVG."""
    try:
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            encoded = base64.b64encode(r.content).decode("utf-8")
            return f"data:image/png;base64,{encoded}"
    except:
        pass
    return "" # Return empty if fails

def shorten_number(num):
    """Formats 1500 to 1.5k, etc."""
    try:
        num = float(num)
    except:
        return "0"
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    if num >= 1000:
        return f"{num/1000:.1f}k"
    return str(int(num))

# --- API ROUTES ---

@app.route('/')
def home():
    return "Discord Server Stats API is Running. Use /api?id=<invite_code>"

@app.route('/api')
def render_stats():
    # 1. Get Arguments
    invite_code = request.args.get('id') or request.args.get('invite')
    owner_id = request.args.get('owner') # User ID for Lanyard (optional)
    text_color = request.args.get('text', 'ffffff')
    bg_color = request.args.get('bg', '23272a')
    
    if not invite_code:
        return Response("Error: Missing 'id' (invite code) parameter.", status=400)

    # 2. Fetch Discord Server Data via Invite API
    discord_data = {
        "name": "Unknown Server",
        "members": "0",
        "online": "0",
        "icon": ""
    }
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true", headers=headers, timeout=5)
        d = r.json()
        
        if r.status_code == 200 and 'guild' in d:
            g = d['guild']
            discord_data['name'] = sanitize_xml(g.get('name', 'Server'))
            discord_data['members'] = d.get('approximate_member_count', 0)
            discord_data['online'] = d.get('approximate_presence_count', 0)
            
            # Fetch Server Icon
            if g.get('icon'):
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=64"
                discord_data['icon'] = get_base64_image(icon_url)
    except Exception as e:
        print(f"Discord API Error: {e}")

    # 3. Fetch Owner/Lanyard Data (Optional)
    lanyard_data = {
        "status_color": "#747f8d", # Grey (offline default)
        "avatar": ""
    }

    if owner_id:
        try:
            r = requests.get(f"https://api.lanyard.rest/v1/users/{owner_id}", timeout=3)
            data = r.json()
            if data['success']:
                kv = data['data']
                discord_status = kv['discord_status']
                
                # Set color based on status
                if discord_status == 'online': lanyard_data['status_color'] = '#43b581'
                elif discord_status == 'idle': lanyard_data['status_color'] = '#faa61a'
                elif discord_status == 'dnd': lanyard_data['status_color'] = '#f04747'
                
                # Get Owner Avatar
                user = kv['discord_user']
                if user.get('avatar'):
                    # GIF check?
                    ext = "gif" if user['avatar'].startswith("a_") else "png"
                    ava_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.{ext}?size=64"
                    lanyard_data['avatar'] = get_base64_image(ava_url)
        except Exception as e:
            print(f"Lanyard API Error: {e}")

    # 4. Construct SVG
    # Logic: If Owner is present, show their pfp. Always show server icon.
    
    width = 300 if owner_id else 250
    height = 100
    
    member_formatted = shorten_number(discord_data['members'])
    online_formatted = shorten_number(discord_data['online'])

    # Icons in SVG
    server_icon_svg = f'<image x="20" y="20" width="60" height="60" href="{discord_data["icon"]}" clip-path="url(#circle)"/>' if discord_data['icon'] else ''
    
    owner_section = ""
    if owner_id and lanyard_data['avatar']:
        # If owner exists, we draw a second bubble
        owner_section = f"""
        <circle cx="260" cy="50" r="30" fill="url(#ownerAvatar)"/>
        <circle cx="282" cy="72" r="8" fill="{lanyard_data['status_color']}" stroke="{bg_color}" stroke-width="2"/>
        <defs>
             <pattern id="ownerAvatar" height="100%" width="100%" patternContentUnits="objectBoundingBox">
                 <image href="{lanyard_data['avatar']}" preserveAspectRatio="none" width="1" height="1" />
             </pattern>
        </defs>
        """

    svg_code = f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
        <style>
            .text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; fill: #{text_color}; }}
            .title {{ font-weight: bold; font-size: 16px; }}
            .stat {{ font-size: 13px; font-weight: 600; fill: #888; }}
            .count {{ font-size: 13px; font-weight: bold; fill: #{text_color}; }}
        </style>
        
        <!-- Background -->
        <rect x="0" y="0" width="{width}" height="{height}" rx="15" fill="#{bg_color}" stroke="#2c2f33" stroke-width="1"/>

        <!-- Clip Path for Server Icon -->
        <defs>
            <clipPath id="circle">
                <circle cx="50" cy="50" r="30" />
            </clipPath>
        </defs>

        <!-- Server Icon -->
        {server_icon_svg}

        <!-- Text Data -->
        <text x="95" y="40" class="text title">{discord_data['name']}</text>
        
        <circle cx="100" cy="65" r="5" fill="#43b581"/>
        <text x="112" y="70" class="stat">Online: <tspan class="count">{online_formatted}</tspan></text>
        
        <circle cx="100" cy="85" r="5" fill="#747f8d"/>
        <text x="112" y="90" class="stat">Members: <tspan class="count">{member_formatted}</tspan></text>

        <!-- Optional Owner Section -->
        {owner_section}

    </svg>
    """

    resp = make_response(svg_code)
    resp.headers['Content-Type'] = 'image/svg+xml'
    # Important: Tell GitHub NOT to cache this for too long so it updates
    resp.headers['Cache-Control'] = 'no-cache, max-age=300' 
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
