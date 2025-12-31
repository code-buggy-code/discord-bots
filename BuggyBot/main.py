import sys
sys.path.append('..')
# UPDATED: Importing Spotify keys from secret_bot for safety!
from secret_bot import TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
import datetime
import asyncio
# import motor.motor_asyncio
import os
import json
import re
import typing

# --- NEW IMPORTS FOR MUSIC ---
from ytmusicapi import YTMusic
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

# ==========================================
#              FUNCTION LIST
# ==========================================
# 1. DatabaseHandler (Class) - Handles MongoDB connections
# 2. clean_id - Cleans mention strings into IDs
# 3. load_initial_config - Loads settings from DB
# 4. save_config_to_db - Saves settings to DB
# 5. is_admin - Checks if user has admin privileges
# 6. load_youtube_service - Connects to YouTube API
# 7. load_music_services - Connects to Spotify & YouTube Music
# 8. process_spotify_link - Converts Spotify links to YouTube
# 9. send_log - Sends logs to the specific channel
# 10. nightly_purge - Deletes messages at 3 AM
# 11. check_token_expiry - Checks if YouTube token is valid
# 12. on_ready - Startup tasks (Now includes immediate license check!)
# 13. on_raw_reaction_add - Handles ticket reactions
# 14. on_member_update - Checks for banned/ticket roles
# 15. setsetting - Overwrites a setting
# 16. addsetting - Adds to a list setting
# 17. removesetting - Removes from a list setting
# 18. showsettings - Displays current settings
# 19. refreshyoutube - Starts OAuth flow
# 20. entercode - Finishes OAuth flow
# 21. stick - Sticks a message
# 22. unstick - Removes a sticky message
# 23. liststickies - Shows active stickies
# 24. purge - Deletes messages
# 25. help - Shows help menu
# 26. on_message - Handles stickies and music links
# 27. on_command_error - Error reporting
# ==========================================

# --- 1. CONFIGURATION & DATABASE SETTINGS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_NAME = "BuggyBotDB"
CONFIG_COLLECTION = "bot_config"
STICKY_COLLECTION = "sticky_messages" 


# --- 🎵 SPOTIFY CONFIGURATION 🎵 ---
# REMOVED: Keys are now loaded from secret_bot.py for safety!

# Default configuration
DEFAULT_CONFIG = {
    "log_channel_id": 0,
    "nightly_channels": [],
    "link_safe_channels": [], 
    "playlist_id": "",
    "music_channel_id": 0,
    "bad_role_to_ban_id": 0,
    "ticket_access_role_id": 0,
    "admin_role_id": [],
    "sticky_delay_seconds": 300,
    "ticket_category_id": 0, 
    "ticket_message": "{mention} Welcome! React to this message to get chat access!", 
    "ticket_channel_name_format": "desperate-{username}",
    "ticket_react_message_id": 0,
    "ticket_react_emoji": "✅",
}

SIMPLE_SETTINGS = {
    "log_channel_id": int,
    "playlist_id": str,
    "music_channel_id": int,
    "bad_role_to_ban_id": int,
    "ticket_access_role_id": int,
    "sticky_delay_seconds": int,
    "ticket_category_id": int,
    "ticket_message": str,
    "ticket_channel_name_format": str,
    "ticket_react_message_id": int,
    "ticket_react_emoji": str,
    "nightly_channels": list,
    "link_safe_channels": list,
    "admin_role_id": list,
}

CHANNEL_LISTS = ["nightly_channels", "link_safe_channels"]
ROLE_LISTS = ["admin_role_id"]
CHANNEL_ID_KEYS = ["log_channel_id", "music_channel_id", "ticket_category_id"]
ROLE_ID_KEYS = ["bad_role_to_ban_id", "ticket_access_role_id"]

config = DEFAULT_CONFIG.copy()
db = None
sticky_data = {} 
is_purging = False
youtube = None
auth_flow = None 
ytmusic = None
spotify = None

# --- 2. DATABASE HANDLER ---
# --- 2. DATABASE HANDLER (LOCAL FILE VERSION) ---
class DatabaseHandler:
    def __init__(self, uri, db_name):
        # We ignore the URI now because we use a local file!
        self.file_path = "database.json"
        self.data = self._load_from_file()

    def _load_from_file(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"bot_config": [], "sticky_messages": []}

    def _save_to_file(self):
        with open(self.file_path, "w") as f:
            # Save dates as text
            json.dump(self.data, f, indent=4, default=str)

    async def load_config(self):
        collection = self.data.get("bot_config", [])
        for doc in collection:
            if doc.get("_id") == "config":
                return doc
        return {}

    async def save_config(self, config_data):
        data_to_save = config_data.copy()
        data_to_save["_id"] = "config"
        
        collection = self.data.get("bot_config", [])
        collection = [d for d in collection if d.get("_id") != "config"]
        collection.append(data_to_save)
        
        self.data["bot_config"] = collection
        self._save_to_file()

    async def load_stickies(self):
        data = {}
        collection = self.data.get("sticky_messages", [])
        for doc in collection:
            time_val = doc.get('last_time')
            if isinstance(time_val, str):
                try:
                    time_val = datetime.datetime.fromisoformat(time_val)
                except:
                    time_val = datetime.datetime.now()

            data[doc['_id']] = [doc['content'], doc['last_msg_id'], time_val]
        return data

    async def save_sticky(self, channel_id, content, last_msg_id, last_time):
        new_doc = {
            "_id": channel_id,
            "content": content,
            "last_msg_id": last_msg_id,
            "last_time": last_time
        }
        
        collection = self.data.get("sticky_messages", [])
        collection = [d for d in collection if d.get("_id") != channel_id]
        collection.append(new_doc)
        
        self.data["sticky_messages"] = collection
        self._save_to_file()

    async def delete_sticky(self, channel_id):
        collection = self.data.get("sticky_messages", [])
        collection = [d for d in collection if d.get("_id") != channel_id]
        self.data["sticky_messages"] = collection
        self._save_to_file()
def clean_id(mention_str):
    return int(re.sub(r'[^0-9]', '', str(mention_str)))

async def load_initial_config():
    global config
    saved_config = await db.load_config()
    config.update(saved_config)
    if "_id" in config: del config["_id"]
    print("Configuration loaded.")

async def save_config_to_db():
    await db.save_config(config)

def is_admin():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        return any(role.id in config['admin_role_id'] for role in ctx.author.roles)
    return commands.check(predicate)

# --- 4. YOUTUBE & SPOTIFY SETUP ---
def load_youtube_service():
    global youtube
    youtube = None
    token_path = os.path.join(BASE_DIR, 'token.json')
    
    try:
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/youtube'])
            # Only use it if it's NOT expired or if we can successfully refresh it
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(token_path, 'w') as token: token.write(creds.to_json())
                except:
                    print("⚠️ Token expired and refresh failed. License update needed.")
                    return False
            
            if creds and not creds.expired:
                youtube = build('youtube', 'v3', credentials=creds)
                return True
        return False
    except Exception as e:
        print(f"YouTube Service Error: {e}")
        return False

def load_music_services():
    global ytmusic, spotify
    try:
        sp_auth = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
        spotify = Spotify(auth_manager=sp_auth)
        print("✅ Spotify Connected!")
    except Exception as e:
        print(f"⚠️ Spotify Error: {e}")
    
    browser_path = os.path.join(BASE_DIR, 'browser.json')
    try:
        if os.path.exists(browser_path):
            ytmusic = YTMusic(browser_path)
            print("✅ YouTube Music Connected!")
        else:
            print(f"⚠️ browser.json not found. Music features limited.")
    except Exception as e:
        print(f"⚠️ YouTube Music Error: {e}")

def process_spotify_link(url):
    if not spotify or not ytmusic: return None
    if not config['playlist_id']: return "⚠️ No playlist ID set in config!"
    
    try:
        if "track" in url:
            track = spotify.track(url)
            artist = track['artists'][0]['name']
            title = track['name']
            search_query = f"{artist} - {title}"
            search_results = ytmusic.search(search_query, filter="songs")
            if not search_results: return f"⚠️ Couldn't find **{title}** on YouTube Music."
            song_id = search_results[0]['videoId']
            ytmusic.add_playlist_items(config['playlist_id'], [song_id])
            return f"🎶 Added **{title}** by **{artist}** to the playlist!"
    except Exception as e:
        print(f"Music Processing Error: {e}")
        return None
    return None

# --- 5. BOT SETUP ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
scheduler = AsyncIOScheduler()

async def send_log(text):
    if config['log_channel_id'] == 0: return
    channel = bot.get_channel(config['log_channel_id'])
    if channel:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        await channel.send(f"`[{timestamp}]` 📝 {text}")

# --- 6. TASKS ---
async def nightly_purge():
    global is_purging
    is_purging = True
    count = 0
    try:
        for channel_id in config['nightly_channels']:
            try:
                channel = bot.get_channel(channel_id)
                if channel:
                    def should_delete(msg):
                        if msg.pinned: return False
                        if channel_id in sticky_data and msg.id == sticky_data[channel_id][1]: return False
                        if channel_id in config.get('link_safe_channels', []) and ("http" in msg.content): return False
                        return True
                    deleted = await channel.purge(limit=None, check=should_delete)
                    count += len(deleted)
            except: pass
        await send_log(f"**Purge Complete:** Deleted {count} messages.")
    finally:
        is_purging = False

async def check_token_expiry(is_startup=False):
    token_path = os.path.join(BASE_DIR, 'token.json')
    if not os.path.exists(token_path):
        if not is_startup: await send_log("⚠️ **License Error:** `token.json` is missing!")
        return

    try:
        with open(token_path, 'r') as f:
            data = json.load(f)
            if 'expiry' in data:
                expiry_time = datetime.datetime.strptime(data['expiry'][:19], "%Y-%m-%dT%H:%M:%S")
                time_left = expiry_time - datetime.datetime.utcnow()
                days = time_left.days
                
                if time_left.total_seconds() <= 0:
                    status = "❌ **EXPIRED**"
                elif days < 1:
                    status = f"⚠️ **URGENT:** Expires in {int(time_left.total_seconds()/3600)}h!"
                else:
                    status = f"✅ Expires in {days} days."

                prefix = "🚀 **Bot Started:** " if is_startup else "📅 **Daily Check:** "
                await send_log(f"{prefix}YouTube License Status: {status}")
    except Exception as e:
        print(f"Expiry Check Error: {e}")

@bot.event
async def on_ready():
    global db, sticky_data
    try:
        db = DatabaseHandler("", DB_NAME)
        # await db.client.admin.command('ping')
        await load_initial_config()
        sticky_data = await db.load_stickies()
    except Exception as e:
        print(f"Database Connection Error: {e}")

    print(f"Hello! I am logged in as {bot.user}")
    load_youtube_service()
    load_music_services()
    
    # Check license immediately on startup!
    await check_token_expiry(is_startup=True)
    
    if not scheduler.running:
        scheduler.add_job(nightly_purge, CronTrigger(hour=3, minute=0, timezone='US/Eastern'))
        scheduler.add_job(check_token_expiry, CronTrigger(hour=4, minute=0, timezone='US/Eastern'))
        scheduler.start()
    
    await send_log("Bot is online and ready!")

# --- 7. EVENTS ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    if payload.message_id == config['ticket_react_message_id'] and str(payload.emoji) == config['ticket_react_emoji']:
        guild = bot.get_guild(payload.guild_id)
        member = payload.member or await guild.fetch_member(payload.user_id)
        raw_name = config['ticket_channel_name_format'].replace("{username}", member.name).replace(" ", "-").lower()
        ticket_name = re.sub(r'[^a-z0-9\-_]', '', raw_name)
        channel = discord.utils.get(guild.text_channels, name=ticket_name)
        if channel:
            try:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
                msg = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
                await send_log(f"🔓 Access granted to **{member.name}**.")
            except: pass

@bot.event
async def on_member_update(before, after):
    if config['bad_role_to_ban_id'] != 0:
        if any(r.id == config['bad_role_to_ban_id'] for r in after.roles) and not any(r.id == config['bad_role_to_ban_id'] for r in before.roles):
            try:
                await after.ban(reason="Auto-ban role assigned")
                await send_log(f"🔨 **BANNED** {after.name} (Reason: Restricted role).")
            except: pass

    if config['ticket_access_role_id'] != 0:
        if any(r.id == config['ticket_access_role_id'] for r in after.roles) and not any(r.id == config['ticket_access_role_id'] for r in before.roles):
            guild = after.guild
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                after: discord.PermissionOverwrite(read_messages=True, send_messages=False)
            }
            for role_id in config['admin_role_id']:
                role = guild.get_role(role_id)
                if role: overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            category = guild.get_channel(config['ticket_category_id']) if config['ticket_category_id'] != 0 else None
            channel_name = config['ticket_channel_name_format'].replace("{username}", after.name).replace(" ", "-").lower()
            try:
                ticket_channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)
                msg_content = config['ticket_message'].replace("{mention}", after.mention)
                sent_msg = await ticket_channel.send(msg_content)
                if config['ticket_react_message_id'] == 0:
                    config['ticket_react_message_id'] = sent_msg.id
                    await save_config_to_db()
                await send_log(f"✅ Ticket created for **{after.name}**.")
            except Exception as e:
                await send_log(f"❌ Failed to create ticket: {e}")

# --- 8. COMMANDS ---
@bot.command()
@is_admin()
async def setsetting(ctx, key: str = None, *, value: str = None):
    if not key or not value: return await ctx.send("❌ Usage: `!setsetting <key> <value>`")
    key = key.lower()
    if key not in SIMPLE_SETTINGS: return await ctx.send(f"❌ Invalid key.")
    try:
        if SIMPLE_SETTINGS[key] == list:
            new_val = [clean_id(i) for i in value.split()]
        elif SIMPLE_SETTINGS[key] == int:
            new_val = clean_id(value)
        else:
            new_val = value
        config[key] = new_val
        await save_config_to_db()
        await ctx.send(f"✅ Saved `{key}` as `{new_val}`.")
    except: await ctx.send("❌ Error: Check value.")

@bot.command()
@is_admin()
async def addsetting(ctx, key: str = None, *, value: str = None):
    if not key or not value: return await ctx.send("❌ Usage: `!addsetting <key> <value>`")
    key = key.lower()
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list: 
        return await ctx.send("❌ Not a list! Use `!setsetting` instead.")
    try:
        to_add = [clean_id(i) for i in value.split()]
        count = 0
        for item in to_add:
            if item not in config[key]:
                config[key].append(item)
                count += 1
        await save_config_to_db()
        await ctx.send(f"✅ Added {count} items.")
    except: await ctx.send("❌ Error.")

@bot.command()
@is_admin()
async def removesetting(ctx, key: str = None, *, value: str = None):
    if not key or not value: return await ctx.send("❌ Usage: `!removesetting <key> <value>`")
    key = key.lower()
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list:
        return await ctx.send("❌ Not a list!")
    try:
        to_remove = [clean_id(i) for i in value.split()]
        count = 0
        for item in to_remove:
            if item in config[key]:
                config[key].remove(item)
                count += 1
        await save_config_to_db()
        await ctx.send(f"✅ Removed {count} items.")
    except: await ctx.send("❌ Error.")

@bot.command()
@is_admin()
async def showsettings(ctx):
    text = "__**Bot Settings**__\n"
    for k, v in config.items():
        if k in SIMPLE_SETTINGS:
            disp = f"`{v}`"
            if k in CHANNEL_ID_KEYS and v != 0: disp = f"<#{v}>"
            elif k in CHANNEL_LISTS: disp = " ".join([f"<#{x}>" for x in v]) if v else "None"
            elif k in ROLE_ID_KEYS: disp = f"<@&{v}>"
            elif k in ROLE_LISTS: disp = " ".join([f"<@&{x}>" for x in v]) if v else "None"
            text += f"**{k}**: {disp}\n"
    await ctx.send(text)

@bot.command()
@is_admin()
async def refreshyoutube(ctx):
    global auth_flow
    secret_path = os.path.join(BASE_DIR, 'client_secret.json')
    if not os.path.exists(secret_path): return await ctx.send("❌ Missing `client_secret.json`!")
    try:
        auth_flow = Flow.from_client_secrets_file(secret_path, scopes=['https://www.googleapis.com/auth/youtube'], redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        auth_url, _ = auth_flow.authorization_url(prompt='consent')
        await ctx.send(f"🔄 **Renewal Started!**\n1. Click: <{auth_url}>\n2. Type: `!entercode YOUR_CODE`")
    except Exception as e: await ctx.send(f"❌ Error: {e}")

@bot.command()
@is_admin()
async def entercode(ctx, code: str):
    global auth_flow
    if not auth_flow: return await ctx.send("❌ Run `!refreshyoutube` first!")
    try:
        auth_flow.fetch_token(code=code)
        token_path = os.path.join(BASE_DIR, 'token.json')
        with open(token_path, 'w') as token: token.write(auth_flow.credentials.to_json())
        load_youtube_service()
        await check_token_expiry()
        await ctx.send("✅ **Success!** License renewed.")
    except Exception as e: await ctx.send(f"❌ Error: {e}")

@bot.command()
@is_admin()
async def stick(ctx, *, text: str):
    msg = await ctx.send(text)
    sticky_data[ctx.channel.id] = [text, msg.id, datetime.datetime.utcnow().timestamp()]
    await db.save_sticky(ctx.channel.id, text, msg.id, sticky_data[ctx.channel.id][2])
    try: await ctx.message.delete()
    except: pass

@bot.command()
@is_admin()
async def unstick(ctx):
    if ctx.channel.id in sticky_data:
        sticky_data.pop(ctx.channel.id)
        await db.delete_sticky(ctx.channel.id)
        await ctx.send("✅ Removed.")

@bot.command()
@is_admin()
async def liststickies(ctx):
    if not sticky_data: return await ctx.send("❌ No stickies.")
    text = "**Active Stickies:**\n"
    for cid, data in sticky_data.items():
        text += f"<#{cid}>: {data[0][:50]}...\n"
    await ctx.send(text)

@bot.command()
@is_admin()
async def purge(ctx, target: typing.Union[discord.Member, str], scope: typing.Union[discord.TextChannel, discord.CategoryChannel, str] = None):
    chans = []
    if scope is None or scope == "channel": chans = [ctx.channel]
    elif isinstance(scope, discord.TextChannel): chans = [scope]
    elif isinstance(scope, discord.CategoryChannel): chans = scope.text_channels
    elif isinstance(scope, str) and scope.lower() == "server": chans = ctx.guild.text_channels

    if len(chans) > 1:
        await ctx.send(f"⚠️ Purging {len(chans)} channels. Type `yes` to confirm.")
        try: await bot.wait_for('message', check=lambda m: m.author == ctx.author and m.content.lower() == 'yes', timeout=15)
        except asyncio.TimeoutError: return await ctx.send("❌ Cancelled.")

    await ctx.send(f"🧹 Purging...")
    total = 0
    def check(msg):
        if msg.pinned: return False
        if msg.channel.id in sticky_data and msg.id == sticky_data[msg.channel.id][1]: return False
        if isinstance(target, discord.Member): return msg.author == target
        return True

    for c in chans:
        try:
            deleted = await c.purge(limit=None, check=check)
            total += len(deleted)
        except: pass
    await ctx.send(f"✅ Deleted {total} messages.")
    await send_log(f"🗑️ **Purge:** {ctx.author.name} deleted {total} messages.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="BuggyBot Help", color=discord.Color.blue())
    embed.add_field(name="⚙️ Settings", value="`!setsetting`, `!addsetting`, `!removesetting`, `!showsettings`", inline=False)
    embed.add_field(name="📌 Sticky", value="`!stick`, `!unstick`, `!liststickies`", inline=False)
    embed.add_field(name="📺 YouTube", value="`!refreshyoutube`, `!entercode`", inline=False)
    embed.add_field(name="🧹 Purge", value="`!purge <user/all> <channel/category/server>`", inline=False)
    embed.add_field(name="🎵 Music", value="Paste Spotify link in music channel!", inline=False)
    await ctx.send(embed=embed)

# --- 9. MESSAGE EVENTS ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.type == discord.MessageType.pins_add: 
        try: await message.delete()
        except: pass
        return

    if message.channel.id in sticky_data:
        content, last_id, last_time = sticky_data[message.channel.id]
        if isinstance(last_time, datetime.datetime): last_time = last_time.timestamp()
        if datetime.datetime.utcnow().timestamp() - last_time > config['sticky_delay_seconds']:
            try:
                if last_id:
                    try:
                        m = await message.channel.fetch_message(last_id)
                        await m.delete()
                    except: pass
                new_msg = await message.channel.send(content)
                sticky_data[message.channel.id][1] = new_msg.id
                sticky_data[message.channel.id][2] = datetime.datetime.utcnow().timestamp()
                await db.save_sticky(message.channel.id, content, new_msg.id, sticky_data[message.channel.id][2])
            except: pass

    if config['music_channel_id'] != 0 and message.channel.id == config['music_channel_id']:
        # FIXED: Now checks for standard Spotify links instead of googleusercontent!
        if "open.spotify.com" in message.content:
             res = await asyncio.to_thread(process_spotify_link, message.content)
             if res:
                 await message.channel.send(res)
                 try: await message.add_reaction("🎵")
                 except: pass
        elif youtube:
            v_id = None
            if "v=" in message.content: v_id = message.content.split("v=")[1].split("&")[0]
            elif "youtu.be/" in message.content: v_id = message.content.split("youtu.be/")[1].split("?")[0]
            if v_id:
                try:
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": v_id}}}).execute()
                    await message.add_reaction("🎵")
                except: pass

    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)): return
    await ctx.send(f"⚠️ **Error:** `{error}`")

bot.run(TOKEN)
