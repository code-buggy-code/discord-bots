"""
🐛 BUGGYBOT MANIFEST 🐛

--- HELPER FUNCTIONS ---
- clean_id(mention_str): Converts mentions to raw IDs.
- load_initial_config(): Loads settings from DB on startup.
- save_config_to_db(): Saves current settings to DB.
- is_admin(): Check to see if user has admin role or permissions.
- load_youtube_service(): Connects to YouTube API (checks DB first, then file).
- load_music_services(): Connects to Spotify and YouTube Music.
- process_spotify_link(url, channel): (ASYNC) steps through the add process and sends logs to chat.
- send_log(text): Sends a message to the log channel.
- check_manager_logs(): Loop that checks for logs from other processes (IPC).
- nightly_purge(): task that deletes messages in specific channels at 3 AM.
- check_token_validity_task(): Daily task to verify YouTube license.

--- DATABASE HANDLER ---
- load_config(): Gets bot config from JSON.
- save_config(config_data): Saves bot config to JSON.
- load_stickies(): Loads active sticky messages.
- save_sticky(...): Saves a new sticky message.
- delete_sticky(channel_id): Removes a sticky message.
- load_votes(): Loads the current vote counts.
- save_vote(target_id, voters): Saves a user's vote list.

--- COMMANDS ---
- !sync: Updates code from GitHub and restarts.
- !checkyoutube: Checks if YouTube API token is valid.
- !setsetting <key> <value>: Sets a config value.
- !addsetting <key> <value>: Adds items to a list config.
- !removesetting <key> <value>: Removes items from a list config.
- !showsettings: Shows all current config values.
- !refreshyoutube: Starts the OAuth flow to renew YouTube license.
- !entercode <code>: Completes the YouTube renewal with the code.
- !stick <text>: Creates a sticky message in the current channel.
- !unstick: Removes the sticky message in the current channel.
- !liststickies: Lists all active sticky messages.
- !purge <target> <scope>: Deletes messages based on filters.
- !vote <user_id>: (Admin) Registers a vote against a user. 3 votes = kick.
- !removevotes <user_id>: (Admin) Removes the most recent vote for a user.
- !showvotes: (Admin) Lists all active votes.
- !help: Shows the help menu (with YouTube & Spotify mentioned).

--- EVENTS ---
- on_ready: Startup sequence.
- on_raw_reaction_add: Handles ticket access via reactions.
- on_member_update: Handles auto-bans and ticket role assignment.
- on_message: Handles Sticky Messages and Music Links (YouTube & Spotify).
"""

import sys
sys.path.append('..')

try:
    from secret_bot import TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
except ImportError:
    from secret_bot import TOKEN
    SPOTIFY_CLIENT_ID = None
    SPOTIFY_CLIENT_SECRET = None

import discord
from discord.ext import commands, tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
import datetime
import asyncio
import os
import json
import re
import typing
import requests
from ytmusicapi import YTMusic
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "BuggyBotDB"
IPC_FILE = os.path.join(BASE_DIR, "pending_logs.json")

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
    "youtube_token_json": "" 
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
vote_data = {} 
is_purging = False
youtube = None
auth_flow = None 
ytmusic = None
spotify = None

# --- DATABASE HANDLER ---
class DatabaseHandler:
    def __init__(self, uri, db_name):
        self.file_path = "database.json"
        self.data = self._load_from_file()

    def _load_from_file(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"bot_config": [], "sticky_messages": [], "votes": []}

    def _save_to_file(self):
        with open(self.file_path, "w") as f:
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
        new_doc = {"_id": channel_id, "content": content, "last_msg_id": last_msg_id, "last_time": last_time}
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

    async def load_votes(self):
        data = {}
        collection = self.data.get("votes", [])
        for doc in collection:
            data[doc['_id']] = doc.get('voters', [])
        return data

    async def save_vote(self, target_id, voters):
        new_doc = {"_id": target_id, "voters": voters}
        collection = self.data.get("votes", [])
        collection = [d for d in collection if d.get("_id") != target_id]
        if voters: 
            collection.append(new_doc)
        self.data["votes"] = collection
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

# --- MUSIC SETUP ---
async def load_youtube_service():
    global youtube
    youtube = None
    
    # 1. Try to load from Database first
    token_json = config.get('youtube_token_json')
    
    # 2. Fallback: Try file (migration)
    if not token_json and os.path.exists(os.path.join(BASE_DIR, 'token.json')):
        with open(os.path.join(BASE_DIR, 'token.json'), 'r') as f:
            token_json = f.read()
    
    if token_json:
        try:
            info = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(info, ['https://www.googleapis.com/auth/youtube'])
            
            # Check validity & Refresh if needed
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # SAVE NEW TOKEN TO DB
                    config['youtube_token_json'] = creds.to_json()
                    await save_config_to_db()
                    print("✅ Refreshed and saved new YouTube token to DB.")
                except Exception as e:
                    print(f"⚠️ Failed to refresh token: {e}")
                    return False
            
            if creds.valid:
                youtube = build('youtube', 'v3', credentials=creds)
                return True
        except Exception as e:
            print(f"YouTube Service Error: {e}")
            return False
    return False

def load_music_services():
    global ytmusic, spotify
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET: return
    try:
        sp_auth = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
        spotify = Spotify(auth_manager=sp_auth)
    except: pass
    
    browser_path = os.path.join(BASE_DIR, 'browser.json')
    try:
        if os.path.exists(browser_path):
            ytmusic = YTMusic(browser_path)
    except: pass

async def process_spotify_link(url, channel):
    """Refactored to find via YTMusic but ADD via the working YouTube API!"""
    
    # Check services first
    if not spotify: 
        await channel.send("❌ **Error:** Spotify service is not loaded.")
        return
    # Note: We need ytmusic to FIND the song, but we use 'youtube' to ADD it.
    if not ytmusic:
        await channel.send("❌ **Error:** YouTube Music service (search) is not loaded.")
        return
    if not youtube:
        await channel.send("❌ **Error:** Main YouTube service (playlist adder) is not loaded. Check `!checkyoutube`.")
        return
    if not config['playlist_id']:
        await channel.send("⚠️ **Error:** No YouTube Playlist ID is set in my settings!")
        return

    # Clean up the URL
    match = re.search(r'(https?://[^\s]+)', url)
    if match: 
        clean_url = match.group(0)
    else:
        clean_url = url

    loop = asyncio.get_running_loop()

    # STEP 1: Ask Spotify
    await channel.send(f"1️⃣ **Checking Spotify API...** (Link: `{clean_url}`)")
    try:
        track = await loop.run_in_executor(None, spotify.track, clean_url)
        artist = track['artists'][0]['name']
        title = track['name']
        await channel.send(f"✅ **Spotify Success:** Identified song as **{title}** by **{artist}**.")
    except Exception as e:
        await channel.send(f"❌ **Spotify Failed:** I couldn't understand that link.\nReason: `{e}`")
        return

    # STEP 2: Search YouTube
    await channel.send(f"2️⃣ **Searching YouTube Music...** for `{artist} - {title}`")
    search_query = f"{artist} - {title}"
    try:
        search_results = await loop.run_in_executor(None, lambda: ytmusic.search(search_query, "songs"))
        if not search_results:
            await channel.send("❌ **YouTube Search Failed:** No results found on YouTube Music.")
            return
        
        song_id = search_results[0]['videoId']
        song_title = search_results[0]['title']
        await channel.send(f"✅ **YouTube Success:** Found video **{song_title}** (ID: `{song_id}`).")
    except Exception as e:
        await channel.send(f"❌ **YouTube Search Crud:** Something broke while searching.\nReason: `{e}`")
        return

    # STEP 3: Add to Playlist (USING THE WORKING YOUTUBE SERVICE)
    await channel.send("3️⃣ **Adding to Playlist...** (Using the working path!)")
    try:
        # We construct the request object...
        req = youtube.playlistItems().insert(
            part="snippet", 
            body={
                "snippet": {
                    "playlistId": config['playlist_id'], 
                    "resourceId": {
                        "kind": "youtube#video", 
                        "videoId": song_id
                    }
                }
            }
        )
        # ...and execute it in the thread executor so it doesn't freeze the bot
        await loop.run_in_executor(None, req.execute)
        
        await channel.send(f"🎉 **DONE!** Successfully added **{title}** to the playlist!")
    except Exception as e:
        await channel.send(f"❌ **Playlist Failed:** I found the song but couldn't add it.\nReason: `{e}`")

# --- BOT SETUP ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
scheduler = AsyncIOScheduler()

async def send_log(text):
    if config['log_channel_id'] == 0: return
    channel = bot.get_channel(config['log_channel_id'])
    if channel:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        await channel.send(f"`[{timestamp}]` 📝 {text}")

@tasks.loop(seconds=5)
async def check_manager_logs():
    if config['log_channel_id'] == 0: return
    if os.path.exists(IPC_FILE):
        try:
            with open(IPC_FILE, "r") as f:
                queue = json.load(f)
            if queue:
                channel = bot.get_channel(config['log_channel_id'])
                if channel:
                    for msg in queue:
                        await channel.send(msg)
                        await asyncio.sleep(1) 
                with open(IPC_FILE, "w") as f:
                    json.dump([], f)
        except Exception as e:
            print(f"Log Read Error: {e}")

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

# Only called by command or scheduler, NOT on startup
async def check_token_validity_task():
    await load_youtube_service() # Refreshes if needed
    if youtube:
        await send_log("📅 **Daily Check:** YouTube License is Active & Valid.")
    else:
        await send_log("❌ **Daily Check:** YouTube License is EXPIRED or BROKEN.")

@bot.event
async def on_ready():
    global db, sticky_data, vote_data
    try:
        db = DatabaseHandler(None, DB_NAME)
        await load_initial_config()
        sticky_data = await db.load_stickies()
        vote_data = await db.load_votes()
    except Exception as e:
        print(f"Database Connection Error: {e}")
    print(f"Hello! I am logged in as {bot.user}")
    
    if not check_manager_logs.is_running():
        check_manager_logs.start()
        print("📬 Mailbox Reader Started!")

    await load_youtube_service() # Loads and Refreshes from DB
    load_music_services()
    
    if not scheduler.running:
        scheduler.add_job(nightly_purge, CronTrigger(hour=3, minute=0, timezone='US/Eastern'))
        scheduler.add_job(check_token_validity_task, CronTrigger(hour=4, minute=0, timezone='US/Eastern'))
        scheduler.start()
    await send_log("Bot is online and ready!")

# --- EVENTS ---
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

# --- COMMANDS ---

@bot.command()
@is_admin()
async def sync(ctx):
    await ctx.send("♻️ **Syncing System...**\n1. Pulling code from GitHub...\n2. Restarting all bots (Give me 10 seconds!)")
    os.system("git pull")
    os.system("pkill -f main.py")

@bot.command()
@is_admin()
async def checkyoutube(ctx):
    """(Admin) REAL check: Tries to talk to Google."""
    is_valid = await load_youtube_service() # This refreshes it if possible
    if is_valid:
        # Check expiry date string from the config
        try:
            data = json.loads(config['youtube_token_json'])
            expiry = data.get('expiry', 'Unknown')
            await ctx.send(f"✅ **License Valid!**\nExpiry Date: `{expiry}`\n*(I successfully refreshed it just now)*")
        except:
            await ctx.send("✅ **License Valid!** (But I couldn't read the date string)")
    else:
        await ctx.send("❌ **License Broken.** I tried to refresh it but failed.")

@bot.command()
@is_admin()
async def setsetting(ctx, key: str = None, *, value: str = None):
    if not key or not value: return await ctx.send("❌ Usage: `!setsetting <key> <value>`")
    key = key.lower()
    if key not in SIMPLE_SETTINGS: return await ctx.send(f"❌ Invalid key.")
    try:
        if SIMPLE_SETTINGS[key] == list: new_val = [clean_id(i) for i in value.split()]
        elif SIMPLE_SETTINGS[key] == int: new_val = clean_id(value)
        else: new_val = value
        config[key] = new_val
        await save_config_to_db()
        await ctx.send(f"✅ Saved `{key}` as `{new_val}`.")
    except: await ctx.send("❌ Error: Check value.")

@bot.command()
@is_admin()
async def addsetting(ctx, key: str = None, *, value: str = None):
    if not key or not value: return await ctx.send("❌ Usage: `!addsetting <key> <value>`")
    key = key.lower()
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list: return await ctx.send("❌ Not a list! Use `!setsetting`.")
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
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list: return await ctx.send("❌ Not a list!")
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
        
        # Save to DB instead of file!
        creds_json = auth_flow.credentials.to_json()
        config['youtube_token_json'] = creds_json
        await save_config_to_db()
        
        await load_youtube_service() # Reload it
        await ctx.send("✅ **Success!** License renewed and saved to Database.")
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
    await ctx.send(f"🧹 Purging...")
    total = 0
    def check(msg):
        if msg.pinned: return False
        if msg.channel.id in sticky_data and msg.id == sticky_data[msg.channel.id][1]: return False
        if isinstance(target, discord.Member): return msg.author == target
        return True
    for c in chans:
        try:
            deleted = await c.purge(limit=None, check=should_delete)
            total += len(deleted)
        except: pass
    await ctx.send(f"✅ Deleted {total} messages.")
    await send_log(f"🗑️ **Purge:** {ctx.author.name} deleted {total} messages.")

@bot.command()
@is_admin()
async def vote(ctx, target_id: str):
    """Adds a vote to a user. 3 votes = kick."""
    try: await ctx.message.delete()
    except: pass
    
    user_id = clean_id(target_id)
    if user_id not in vote_data:
        vote_data[user_id] = []
    
    if ctx.author.id in vote_data[user_id]:
        # Don't delete, just warn? Or maybe just let them vote again if admins want to pile on? 
        # Standard logic usually allows unique votes.
        pass

    vote_data[user_id].append(ctx.author.id)
    await db.save_vote(user_id, vote_data[user_id])
    
    await send_log(f"🗳️ **VOTE:** <@{ctx.author.id}> voted for <@{user_id}>. (Total: {len(vote_data[user_id])})")
    
    if len(vote_data[user_id]) >= 3:
        guild = ctx.guild
        member = guild.get_member(user_id)
        if member:
            try:
                await member.kick(reason="Received 3 votes from admins.")
                await send_log(f"🦶 **KICKED:** <@{user_id}> was kicked after receiving 3 votes.")
            except Exception as e:
                await send_log(f"❌ Failed to kick <@{user_id}>: {e}")
        else:
            await send_log(f"⚠️ User <@{user_id}> reached 3 votes but is not in the server.")

@bot.command()
@is_admin()
async def removevotes(ctx, target_id: str):
    """Removes the most recent vote from a user."""
    user_id = clean_id(target_id)
    if user_id in vote_data and vote_data[user_id]:
        removed = vote_data[user_id].pop()
        await db.save_vote(user_id, vote_data[user_id])
        await ctx.send(f"✅ Removed one vote from <@{user_id}> (Originally by <@{removed}>).")
    else:
        await ctx.send(f"❌ No votes found for <@{user_id}>.")

@bot.command()
@is_admin()
async def showvotes(ctx):
    """Lists current active votes."""
    if not vote_data:
        return await ctx.send("📝 No active votes.")
    
    text = "**Current Votes:**\n"
    for uid, voters in vote_data.items():
        if len(voters) > 0:
            voter_list = ", ".join([f"<@{v}>" for v in voters])
            text += f"• <@{uid}>: {len(voters)} votes ({voter_list})\n"
    await ctx.send(text)

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="BuggyBot Help", color=discord.Color.blue())
    embed.add_field(name="⚙️ Settings", value="`!setsetting`, `!addsetting`, `!removesetting`, `!showsettings`", inline=False)
    embed.add_field(name="📌 Sticky", value="`!stick`, `!unstick`, `!liststickies`", inline=False)
    embed.add_field(name="♻️ System", value="`!sync` (Update & Restart)", inline=False)
    embed.add_field(name="📺 YouTube", value="`!refreshyoutube`, `!entercode`, `!checkyoutube`", inline=False)
    embed.add_field(name="🗳️ Votes (Admin)", value="`!vote`, `!removevotes`, `!showvotes`", inline=False)
    embed.add_field(name="🧹 Purge", value="`!purge <user/all> <channel/category/server>`", inline=False)
    embed.add_field(name="🎵 Music", value="Paste YouTube or Spotify links in the music channel!", inline=False)
    await ctx.send(embed=embed)

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
                    try: m = await message.channel.fetch_message(last_id); await m.delete()
                    except: pass
                new_msg = await message.channel.send(content)
                sticky_data[message.channel.id][1] = new_msg.id
                sticky_data[message.channel.id][2] = datetime.datetime.utcnow().timestamp()
                await db.save_sticky(message.channel.id, content, new_msg.id, sticky_data[message.channel.id][2])
            except: pass
            
    # Check for music links
    if config['music_channel_id'] != 0 and message.channel.id == config['music_channel_id']:
        
        # 1. Check for ANY Google/Spotify link (ignores the number at the end!)
        # matches: http://googleusercontent.com/spotify.com/ANYTHING
        if "http://googleusercontent.com/spotify.com/" in message.content.lower() and "http" in message.content.lower():
             await message.channel.send("👀 **I see a Spotify link!** Starting process...")
             await process_spotify_link(message.content, message.channel)
        
        # 2. Check for ANY standard Spotify link
        elif "open.spotify.com/track" in message.content.lower():
             await message.channel.send("👀 **I see a standard Spotify link!** Starting process...")
             await process_spotify_link(message.content, message.channel)

        # 3. Check for YouTube links (fallback)
        elif youtube:
            v_id = None
            if "v=" in message.content: v_id = message.content.split("v=")[1].split("&")[0]
            elif "youtu.be/" in message.content: v_id = message.content.split("youtu.be/")[1].split("?")[0]
            if v_id:
                try: youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": v_id}}}).execute(); await message.add_reaction("🎵")
                except: pass
    
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)): return
    await ctx.send(f"⚠️ **Error:** `{error}`")

bot.run(TOKEN)
