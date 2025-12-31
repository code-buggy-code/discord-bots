import sys
sys.path.append('..')
# Safer import: won't crash if music keys are missing
try:
    from secret_bot import TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
except ImportError:
    from secret_bot import TOKEN
    SPOTIFY_CLIENT_ID = None
    SPOTIFY_CLIENT_SECRET = None

import discord
from discord.ext import commands, tasks # Added 'tasks' for the loop!
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
from ytmusicapi import YTMusic
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "BuggyBotDB"
IPC_FILE = os.path.join(BASE_DIR, "pending_logs.json") # <--- The Mailbox File

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
            return {"bot_config": [], "sticky_messages": []}

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
def load_youtube_service():
    global youtube
    youtube = None
    token_path = os.path.join(BASE_DIR, 'token.json')
    try:
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/youtube'])
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(token_path, 'w') as token: token.write(creds.to_json())
                except:
                    return False
            if creds and not creds.expired:
                youtube = build('youtube', 'v3', credentials=creds)
                return True
        return False
    except: return False

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
    except: return None
    return None

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

# --- NEW: MAILBOX READER TASK ---
@tasks.loop(seconds=5)
async def check_manager_logs():
    """Checks the 'pending_logs.json' file for messages from Manager.py"""
    if config['log_channel_id'] == 0: return

    if os.path.exists(IPC_FILE):
        try:
            with open(IPC_FILE, "r") as f:
                queue = json.load(f)
            
            if queue:
                channel = bot.get_channel(config['log_channel_id'])
                if channel:
                    for msg in queue:
                        # Send the message!
                        await channel.send(msg)
                        await asyncio.sleep(1) 
                
                # Clear the mailbox now that we sent them
                with open(IPC_FILE, "w") as f:
                    json.dump([], f)
        except Exception as e:
            print(f"Log Read Error: {e}")

async def check_token_expiry(is_startup=False):
    token_path = os.path.join(BASE_DIR, 'token.json')
    if not os.path.exists(token_path): return
    try:
        with open(token_path, 'r') as f:
            data = json.load(f)
            if 'expiry' in data:
                expiry_time = datetime.datetime.strptime(data['expiry'][:19], "%Y-%m-%dT%H:%M:%S")
                time_left = expiry_time - datetime.datetime.utcnow()
                days = time_left.days
                if time_left.total_seconds() <= 0: status = "❌ **EXPIRED**"
                elif days < 1: status = f"⚠️ **URGENT:** Expires in {int(time_left.total_seconds()/3600)}h!"
                else: status = f"✅ Expires in {days} days."
                prefix = "🚀 **Bot Started:** " if is_startup else "📅 **Daily Check:** "
                await send_log(f"{prefix}YouTube License Status: {status}")
    except: pass

@bot.event
async def on_ready():
    global db, sticky_data
    try:
        db = DatabaseHandler(None, DB_NAME)
        await load_initial_config()
        sticky_data = await db.load_stickies()
    except Exception as e:
        print(f"Database Connection Error: {e}")
    print(f"Hello! I am logged in as {bot.user}")
    
    # START THE MAILBOX CHECKER
    if not check_manager_logs.is_running():
        check_manager_logs.start()
        print("📬 Mailbox Reader Started!")

    load_youtube_service()
    load_music_services()
    await check_token_expiry(is_startup=True)
    if not scheduler.running:
        scheduler.add_job(check_token_expiry, CronTrigger(hour=4, minute=0, timezone='US/Eastern'))
        scheduler.start()
    await send_log("Bot is online and ready!")

# --- COMMANDS ---

@bot.command()
@is_admin()
async def sync(ctx):
    """(Admin) Pulls changes from GitHub and restarts all bots."""
    await ctx.send("♻️ **Syncing System...**\n1. Pulling code from GitHub...\n2. Restarting all bots (Give me 10 seconds!)")
    os.system("git pull")
    os.system("pkill -f main.py") # Kills everyone; Manager will revive them!

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
            deleted = await c.purge(limit=None, check=check)
            total += len(deleted)
        except: pass
    await ctx.send(f"✅ Deleted {total} messages.")

@bot.event
async def on_message(message):
    if message.author.bot: return
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
    if config['music_channel_id'] != 0 and message.channel.id == config['music_channel_id']:
        if "open.spotify.com" in message.content:
             res = await asyncio.to_thread(process_spotify_link, message.content)
             if res: await message.channel.send(res)
        elif youtube:
            v_id = None
            if "v=" in message.content: v_id = message.content.split("v=")[1].split("&")[0]
            elif "youtu.be/" in message.content: v_id = message.content.split("youtu.be/")[1].split("?")[0]
            if v_id:
                try: youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": v_id}}}).execute(); await message.add_reaction("🎵")
                except: pass
    await bot.process_commands(message)

bot.run(TOKEN)
