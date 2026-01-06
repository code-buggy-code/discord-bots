"""
🐛 BUGGYBOT MANIFEST 🐛

--- HELPER FUNCTIONS ---
- clean_id(mention_str): Converts mentions to raw IDs.
- load_initial_config(): Loads settings from DB on startup.
- save_config_to_db(): Saves current settings to DB.
- is_admin(): Check to see if user has admin role or permissions.
- load_youtube_service(): Connects to YouTube API.
- load_music_services(): Connects to Spotify and YouTube Music.
- process_spotify_link(url): (ASYNC) Processes Spotify link.
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
- !vote <user_id>: (Admin) Registers a vote against a user.
- !removevotes <user_id>: (Admin) Removes the most recent vote.
- !showvotes: (Admin) Lists all active votes.
- !help: Shows the help menu.

--- NEW COMMANDS (UPDATED) ---
- !purge <target> <scope/number>: (Updated) Purge with 'nonmedia' and confirmation.
- !mediaonly <add/remove> <channel_id>: Sets media-only channels.
- !listmediaonly: Lists media-only channels.
- !dmroles <r1> <r2> <r3>: Sets the 3 DM roles.
- !dmreacts <e1> <e2>: Sets the 2 DM reaction emojis.
- !setdmmessage <0-4> <msg>: Sets DM preset messages.
- !dmreq <add/remove> <channel_id>: Sets DM request channels.
- !listdmreq: Lists DM request settings.

--- EVENTS ---
- on_ready: Startup sequence.
- on_raw_reaction_add: Handles ticket access and DM Request Logic.
- on_member_update: Handles auto-bans and ticket role assignment.
- on_message: Handles Sticky, Music, Media Only (w/ 5min timer), and DM Request logic.
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
    "youtube_token_json": "",
    
    # --- NEW FEATURES ---
    "media_only_channels": [],
    "dm_req_channels": [],
    "dm_roles": [0, 0, 0], # [Role 1, Role 2, Role 3]
    "dm_reacts": ["👍", "👎"], # [React 1, React 2]
    "dm_messages": {
        "0": "{mention} Please include text with your mention to make a request.",
        "1": "Request Accepted!",
        "2": "Request Denied.",
        "3": "DM Request (Role 2) sent to {requested_nickname}.",
        "4": "DM Request (Role 3) sent to {requested_nickname}."
    }
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
    "media_only_channels": list,
    "dm_req_channels": list
}

CHANNEL_LISTS = ["nightly_channels", "link_safe_channels", "media_only_channels", "dm_req_channels"]
ROLE_LISTS = ["admin_role_id"]
CHANNEL_ID_KEYS = ["log_channel_id", "music_channel_id", "ticket_category_id"]
ROLE_ID_KEYS = ["bad_role_to_ban_id", "ticket_access_role_id"]

config = DEFAULT_CONFIG.copy()
db = None
sticky_data = {} 
vote_data = {} 
media_cooldowns = {} # Stores (user_id, channel_id): timestamp
is_purging = False
youtube = None
auth_flow = None 
ytmusic = None
spotify = None

# --- DATABASE HANDLER ---
class DatabaseHandler:
    def __init__(self, uri, db_name):
        self.file_path = os.path.join(BASE_DIR, "database.json")
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
            try:
                cid = int(doc.get('_id', 0))
                if cid == 0: continue
                time_val = doc.get('last_time')
                if time_val is None: time_val = 0.0
                elif isinstance(time_val, str):
                    try: time_val = datetime.datetime.fromisoformat(time_val).timestamp()
                    except: time_val = datetime.datetime.utcnow().timestamp()
                
                content = doc.get('content', "")
                last_msg_id = doc.get('last_msg_id', 0)
                data[cid] = [content, last_msg_id, time_val]
            except Exception as e:
                print(f"Skipping bad sticky entry: {e}")
        return data

    async def save_sticky(self, channel_id, content, last_msg_id, last_time):
        new_doc = {"_id": int(channel_id), "content": content, "last_msg_id": last_msg_id, "last_time": last_time}
        collection = self.data.get("sticky_messages", [])
        collection = [d for d in collection if int(d.get("_id", 0)) != int(channel_id)]
        collection.append(new_doc)
        self.data["sticky_messages"] = collection
        self._save_to_file()

    async def delete_sticky(self, channel_id):
        collection = self.data.get("sticky_messages", [])
        collection = [d for d in collection if int(d.get("_id", 0)) != int(channel_id)]
        self.data["sticky_messages"] = collection
        self._save_to_file()

    async def load_votes(self):
        data = {}
        collection = self.data.get("votes", [])
        for doc in collection:
            try: data[int(doc['_id'])] = doc.get('voters', [])
            except: pass
        return data

    async def save_vote(self, target_id, voters):
        new_doc = {"_id": target_id, "voters": voters}
        collection = self.data.get("votes", [])
        collection = [d for d in collection if d.get("_id") != target_id]
        if voters: collection.append(new_doc)
        self.data["votes"] = collection
        self._save_to_file()

def clean_id(mention_str):
    return int(re.sub(r'[^0-9]', '', str(mention_str)))

async def load_initial_config():
    global config
    saved_config = await db.load_config()
    config.update(saved_config)
    
    # Ensure nested structures exist
    if "dm_roles" not in config: config["dm_roles"] = [0, 0, 0]
    if "dm_reacts" not in config: config["dm_reacts"] = ["👍", "👎"]
    if "dm_messages" not in config: config["dm_messages"] = DEFAULT_CONFIG["dm_messages"]

    if "_id" in config: del config["_id"]
    print("Configuration loaded.")

async def save_config_to_db():
    await db.save_config(config)

def is_admin():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        return any(role.id in config['admin_role_id'] for role in ctx.author.roles)
    return commands.check(predicate)

# --- MUSIC SETUP ---
async def load_youtube_service():
    global youtube
    youtube = None
    token_json = config.get('youtube_token_json')
    if not token_json and os.path.exists(os.path.join(BASE_DIR, 'token.json')):
        with open(os.path.join(BASE_DIR, 'token.json'), 'r') as f:
            token_json = f.read()
    if token_json:
        try:
            info = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(info, ['https://www.googleapis.com/auth/youtube'])
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    config['youtube_token_json'] = creds.to_json()
                    await save_config_to_db()
                except: return False
            if creds.valid:
                youtube = build('youtube', 'v3', credentials=creds)
                return True
        except: return False
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
        if os.path.exists(browser_path): ytmusic = YTMusic(browser_path)
    except: pass

async def process_spotify_link(url):
    if not spotify or not ytmusic or not youtube or not config['playlist_id']: return False
    match = re.search(r'(https?://[^\s]+)', url)
    clean_url = match.group(0) if match else url
    loop = asyncio.get_running_loop()
    try:
        track = await loop.run_in_executor(None, spotify.track, clean_url)
        search_query = f"{track['artists'][0]['name']} - {track['name']}"
        search_results = await loop.run_in_executor(None, lambda: ytmusic.search(search_query, "songs"))
        if not search_results: return False
        req = youtube.playlistItems().insert(
            part="snippet", 
            body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": search_results[0]['videoId']}}}
        )
        await loop.run_in_executor(None, req.execute)
        return True
    except: return False

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
            with open(IPC_FILE, "r") as f: queue = json.load(f)
            if queue:
                channel = bot.get_channel(config['log_channel_id'])
                if channel:
                    for msg in queue: await channel.send(msg); await asyncio.sleep(1) 
                with open(IPC_FILE, "w") as f: json.dump([], f)
        except: pass

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
    finally: is_purging = False

async def check_token_validity_task():
    await load_youtube_service() 
    if youtube: await send_log("📅 **Daily Check:** YouTube License is Active & Valid.")
    else: await send_log("❌ **Daily Check:** YouTube License is EXPIRED or BROKEN.")

@bot.event
async def on_ready():
    global db, sticky_data, vote_data
    try:
        db = DatabaseHandler(None, DB_NAME)
        await load_initial_config()
        sticky_data = await db.load_stickies()
        vote_data = await db.load_votes()
    except Exception as e: print(f"DB Error: {e}")
    print(f"Hello! I am logged in as {bot.user}")
    
    if not check_manager_logs.is_running(): check_manager_logs.start()
    await load_youtube_service()
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
    
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    member = payload.member or await guild.fetch_member(payload.user_id)
    channel = bot.get_channel(payload.channel_id)

    # 1. Ticket System
    if payload.message_id == config['ticket_react_message_id'] and str(payload.emoji) == config['ticket_react_emoji']:
        raw_name = config['ticket_channel_name_format'].replace("{username}", member.name).replace(" ", "-").lower()
        ticket_name = re.sub(r'[^a-z0-9\-_]', '', raw_name)
        c = discord.utils.get(guild.text_channels, name=ticket_name)
        if c:
            try:
                await c.set_permissions(member, read_messages=True, send_messages=True)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
                await send_log(f"🔓 Access granted to **{member.name}**.")
            except: pass

    # 2. DM Request System (Role 1 Flow)
    # Check if channel is a DM Req Channel
    if channel.id in config['dm_req_channels']:
        # Check if emoji is one of the approved DM reactions
        if str(payload.emoji) in config['dm_reacts']:
            try:
                message = await channel.fetch_message(payload.message_id)
                
                # Check if the reactor is one of the users MENTIONED in the message
                if member in message.mentions:
                    
                    # Determine which message to send
                    # Emoji 0 -> Message 1 (Accepted)
                    # Emoji 1 -> Message 2 (Denied)
                    msg_index = -1
                    if str(payload.emoji) == config['dm_reacts'][0]: msg_index = "1"
                    elif str(payload.emoji) == config['dm_reacts'][1]: msg_index = "2"
                    
                    if msg_index != -1:
                        raw_msg = config['dm_messages'].get(msg_index, "")
                        formatted_msg = raw_msg.replace("{mention}", message.author.mention).replace("{requester}", message.author.mention).replace("{requested_nickname}", member.display_name)
                        await channel.send(formatted_msg)
                        
            except Exception as e:
                print(f"DM Req Error: {e}")

@bot.event
async def on_member_update(before, after):
    # Auto Ban
    if config['bad_role_to_ban_id'] != 0:
        if any(r.id == config['bad_role_to_ban_id'] for r in after.roles) and not any(r.id == config['bad_role_to_ban_id'] for r in before.roles):
            try: await after.ban(reason="Auto-ban role assigned"); await send_log(f"🔨 **BANNED** {after.name}.")
            except: pass

    # Ticket Access
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
            except Exception as e: await send_log(f"❌ Failed to create ticket: {e}")

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
    is_valid = await load_youtube_service() 
    if is_valid: await ctx.send(f"✅ **License Valid!**")
    else: await ctx.send("❌ **License Broken.**")

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
            if item not in config[key]: config[key].append(item); count += 1
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
            if item in config[key]: config[key].remove(item); count += 1
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
        config['youtube_token_json'] = auth_flow.credentials.to_json()
        await save_config_to_db()
        await load_youtube_service() 
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

# --- NEW / UPDATED COMMANDS ---

@bot.command()
@is_admin()
async def purge(ctx, target_arg: str, scope_or_num: str = None):
    """
    !purge <@user/nonmedia/all> <number/channel/category/server>
    """
    
    # 1. Parse Target
    target_user = None
    target_mode = "all"
    
    if target_arg.lower() == "all": target_mode = "all"
    elif target_arg.lower() == "nonmedia": target_mode = "nonmedia"
    else:
        try: target_user = await commands.MemberConverter().convert(ctx, target_arg)
        except: return await ctx.send("❌ Invalid target. Use `@user`, `nonmedia`, or `all`.")

    # 2. Parse Scope / Limit
    limit = None
    channels = [ctx.channel]
    
    if scope_or_num:
        if scope_or_num.isdigit():
            limit = int(scope_or_num)
        elif scope_or_num.lower() == "server":
            channels = ctx.guild.text_channels
        else:
            try:
                thing = await commands.GuildChannelConverter().convert(ctx, scope_or_num)
                if isinstance(thing, discord.TextChannel): channels = [thing]
                elif isinstance(thing, discord.CategoryChannel): channels = thing.text_channels
            except: return await ctx.send("❌ Invalid scope or number.")

    # 3. Confirmation
    display_target = target_user.mention if target_user else target_mode.upper()
    display_limit = str(limit) if limit else "ALL"
    display_scope = f"{len(channels)} Channel(s)"
    
    confirm_msg = await ctx.send(
        f"⚠️ **CONFIRM PURGE**\n"
        f"🎯 Target: {display_target}\n"
        f"📂 Scope: {display_scope}\n"
        f"🔢 Limit: {display_limit} messages\n\n"
        f"Type `yes` to confirm."
    )
    
    def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"
    try: await bot.wait_for("message", check=check, timeout=30)
    except: return await ctx.send("❌ Timed out.")

    # 4. Execution
    await ctx.send(f"🧹 Purging...")
    total = 0
    
    def check_msg(msg):
        if msg.pinned: return False
        if msg.channel.id in sticky_data and msg.id == sticky_data[msg.channel.id][1]: return False
        
        # Target Logic
        if target_user:
            return msg.author == target_user
        elif target_mode == "nonmedia":
            has_media = bool(msg.attachments) or bool(msg.embeds) or ("http" in msg.content)
            return not has_media
        return True # 'all'

    for c in channels:
        try:
            deleted = await c.purge(limit=limit, check=check_msg)
            total += len(deleted)
        except: pass

    await ctx.send(f"✅ Deleted {total} messages.")
    await send_log(f"🗑️ **Purge:** {ctx.author.name} deleted {total} messages ({target_mode}).")

@bot.command()
@is_admin()
async def mediaonly(ctx, action: str, channel_id: str):
    cid = clean_id(channel_id)
    if action.lower() == "add":
        if cid not in config['media_only_channels']:
            config['media_only_channels'].append(cid)
            await save_config_to_db()
            await ctx.send(f"✅ Channel <#{cid}> is now **Media Only**.")
        else: await ctx.send("⚠️ Already in list.")
    elif action.lower() == "remove":
        if cid in config['media_only_channels']:
            config['media_only_channels'].remove(cid)
            await save_config_to_db()
            await ctx.send(f"✅ Removed <#{cid}> from Media Only list.")
        else: await ctx.send("⚠️ Not in list.")

@bot.command()
@is_admin()
async def listmediaonly(ctx):
    if not config['media_only_channels']: return await ctx.send("📂 No Media Only channels.")
    text = "📷 **Media Only Channels:**\n" + " ".join([f"<#{c}>" for c in config['media_only_channels']])
    await ctx.send(text)

@bot.command()
@is_admin()
async def dmroles(ctx, r1: discord.Role, r2: discord.Role, r3: discord.Role):
    config['dm_roles'] = [r1.id, r2.id, r3.id]
    await save_config_to_db()
    await ctx.send(f"✅ **DM Roles Set:**\n1. {r1.name}\n2. {r2.name}\n3. {r3.name}")

@bot.command()
@is_admin()
async def dmreacts(ctx, e1: str, e2: str):
    config['dm_reacts'] = [e1, e2]
    await save_config_to_db()
    await ctx.send(f"✅ **DM Reacts Set:** {e1} (Accept) and {e2} (Deny)")

@bot.command()
@is_admin()
async def setdmmessage(ctx, index: str, *, message: str):
    if index not in ["0", "1", "2", "3", "4"]: return await ctx.send("❌ Index must be 0-4.")
    config['dm_messages'][index] = message
    await save_config_to_db()
    await ctx.send(f"✅ **Message {index} Updated.**")

@bot.command()
@is_admin()
async def dmreq(ctx, action: str, channel_id: str):
    cid = clean_id(channel_id)
    if action.lower() == "add":
        if cid not in config['dm_req_channels']:
            config['dm_req_channels'].append(cid)
            await save_config_to_db()
            await ctx.send(f"✅ Channel <#{cid}> is now a **DM Request Channel**.")
        else: await ctx.send("⚠️ Already in list.")
    elif action.lower() == "remove":
        if cid in config['dm_req_channels']:
            config['dm_req_channels'].remove(cid)
            await save_config_to_db()
            await ctx.send(f"✅ Removed <#{cid}> from DM Request list.")
        else: await ctx.send("⚠️ Not in list.")

@bot.command()
@is_admin()
async def listdmreq(ctx):
    text = "**📨 DM Request Settings**\n"
    text += f"**Channels:** {' '.join([f'<#{c}>' for c in config['dm_req_channels']]) if config['dm_req_channels'] else 'None'}\n"
    text += f"**Roles:** <@&{config['dm_roles'][0]}>, <@&{config['dm_roles'][1]}>, <@&{config['dm_roles'][2]}>\n"
    text += f"**Reacts:** {config['dm_reacts'][0]} {config['dm_reacts'][1]}\n"
    await ctx.send(text)

@bot.command()
@is_admin()
async def vote(ctx, target_id: str):
    try: await ctx.message.delete()
    except: pass
    user_id = clean_id(target_id)
    if user_id not in vote_data: vote_data[user_id] = []
    if ctx.author.id in vote_data[user_id]: pass
    vote_data[user_id].append(ctx.author.id)
    await db.save_vote(user_id, vote_data[user_id])
    await send_log(f"🗳️ **VOTE:** <@{ctx.author.id}> voted for <@{user_id}>. (Total: {len(vote_data[user_id])})")
    if len(vote_data[user_id]) >= 3:
        guild = ctx.guild
        member = guild.get_member(user_id)
        if member:
            try: await member.kick(reason="Received 3 votes from admins."); await send_log(f"🦶 **KICKED:** <@{user_id}>.")
            except: pass

@bot.command()
@is_admin()
async def removevotes(ctx, target_id: str):
    user_id = clean_id(target_id)
    if user_id in vote_data and vote_data[user_id]:
        removed = vote_data[user_id].pop()
        await db.save_vote(user_id, vote_data[user_id])
        await ctx.send(f"✅ Removed one vote from <@{user_id}>.")
    else: await ctx.send(f"❌ No votes found.")

@bot.command()
@is_admin()
async def showvotes(ctx):
    if not vote_data: return await ctx.send("📝 No active votes.")
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
    embed.add_field(name="🧹 Purge", value="`!purge <user/nonmedia/all> <limit/scope>`", inline=False)
    embed.add_field(name="📷 Media Only", value="`!mediaonly`, `!listmediaonly`", inline=False)
    embed.add_field(name="📨 DM Requests", value="`!dmreq`, `!dmroles`, `!setdmmessage`, `!listdmreq`", inline=False)
    embed.add_field(name="♻️ System", value="`!sync`", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.type == discord.MessageType.pins_add: 
        try: await message.delete(); return
        except: pass

    # --- 1. MEDIA ONLY CHANNELS ---
    if message.channel.id in config['media_only_channels']:
        is_media = message.attachments or message.embeds or "http" in message.content
        
        if is_media:
            # User posted media, grant them 5 minutes of chat text
            media_cooldowns[(message.author.id, message.channel.id)] = datetime.datetime.utcnow().timestamp()
        else:
            # User posted text only. Check if they have "credit"
            last_time = media_cooldowns.get((message.author.id, message.channel.id), 0)
            if datetime.datetime.utcnow().timestamp() - last_time > 300: # 300 seconds = 5 mins
                try: await message.delete()
                except: pass
                return
            # If we get here, they are within the 5 minute window, so we allow it.

    # --- 2. DM REQUEST CHANNELS ---
    if message.channel.id in config['dm_req_channels']:
        has_text = bool(message.content.strip())
        has_mention = bool(message.mentions)
        
        # Validation: Must have Mention AND Text
        if has_mention and not has_text:
            # Send Message 0 (Ephemeral/Temporary warning)
            # "if it's only a mention without text, message 0 is sent"
            try:
                await message.delete()
                raw_msg = config['dm_messages'].get("0", "Error: No text.")
                formatted_msg = raw_msg.replace("{mention}", message.author.mention).replace("{requester}", message.author.mention)
                await message.channel.send(formatted_msg, delete_after=5)
            except: pass
            return
        
        if not has_mention:
            # No mention = Delete (Strict mode implied)
            try: await message.delete()
            except: pass
            return
            
        # If we got here, it's valid (Mention + Text)
        # Process logic for the mentioned user(s)
        for target in message.mentions:
            if target.bot: continue
            
            # Check Roles
            has_role_1 = any(r.id == config['dm_roles'][0] for r in target.roles)
            has_role_2 = any(r.id == config['dm_roles'][1] for r in target.roles)
            has_role_3 = any(r.id == config['dm_roles'][2] for r in target.roles)
            
            raw_msg = ""
            if has_role_1:
                # Bot reacts with the 2 emojis
                try:
                    for e in config['dm_reacts']: await message.add_reaction(e)
                except: pass
            
            elif has_role_2:
                # Send Message 3
                raw_msg = config['dm_messages'].get("3", "")
                
            elif has_role_3:
                # Send Message 4
                raw_msg = config['dm_messages'].get("4", "")
            
            else:
                # No Roles
                await message.channel.send("sorry they dont have dm roles yet :sob:, buggy's working on this")
            
            if raw_msg:
                formatted_msg = raw_msg.replace("{mention}", message.author.mention).replace("{requester}", message.author.mention).replace("{requested_nickname}", target.display_name)
                await message.channel.send(formatted_msg)

    # --- FIXED STICKY MESSAGES ---
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
            
    # --- MUSIC LINKS ---
    if config['music_channel_id'] != 0 and message.channel.id == config['music_channel_id']:
        if "spotify.com" in message.content.lower():
             success = await process_spotify_link(message.content)
             if success: await message.add_reaction("🎵")
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
