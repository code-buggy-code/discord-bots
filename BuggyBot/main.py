"""
🐛 BUGGYBOT MANIFEST 🐛

--- HELPER FUNCTIONS ---
- clean_id(mention_str): Converts mentions to raw IDs.
- load_initial_config(): Loads settings from DB on startup.
- save_config_to_db(): Saves current settings to DB.
- is_admin_check(interaction): Check to see if user has admin role or permissions (for Slash Commands).
- load_youtube_service(): Connects to YouTube API.
- load_music_services(): Connects to Spotify and YouTube Music.
- process_spotify_link(url): (ASYNC) Processes Spotify link.
- send_log(text): Sends a message to the log channel.
- check_manager_logs(): Loop that checks for logs from other processes (IPC).
- nightly_purge(): task that deletes messages in specific channels at 3 AM.
- check_token_validity_task(): Daily task to verify YouTube license.
- task_loop(): (New) Robust minute-by-minute timer for nightly tasks AND lockout checks.
- handle_sleep_command(message, target_member): Moves users to Sleep VC.
- is_time_in_range(start, end, current): Helper for lockout time checking.

--- DATABASE HANDLER ---
- load_config(): Gets bot config from JSON.
- save_config(config_data): Saves bot config to JSON.
- load_stickies(): Loads active sticky messages.
- save_sticky(...): Saves a new sticky message.
- delete_sticky(channel_id): Removes a sticky message.
- load_votes(): Loads the current vote counts.
- save_vote(target_id, voters): Saves a user's vote list.
- load_tasks(): Loads active task lists (BetterBuggy).
- save_task(task_data): Saves/Updates a task list.
- delete_task(message_id): Removes a completed task list.
- get_user_lockout(user_id): Gets lockout data for a user (MamaBug).
- save_user_lockout(user_id, data): Saves lockout data.
- delete_user_lockout(user_id): Deletes lockout data.

--- UI CLASSES ---
- TaskView: Handles the Buttons (Done, Skip, Undo) for Task Lists.

--- SLASH COMMANDS ---
- /sync: Updates code from GitHub and restarts.
- /checkyoutube: Checks if YouTube API token is valid.
- /setsetting <key> <value>: Sets a config value.
- /addsetting <key> <value>: Adds items to a list config.
- /removesetting <key> <value>: Removes items from a list config.
- /showsettings: Shows all current config values.
- /refreshyoutube: Starts the OAuth flow to renew YouTube license.
- /entercode <code>: Completes the YouTube renewal with the code.
- /stick <text>: Creates a sticky message in the current channel.
- /unstick: Removes the sticky message in the current channel.
- /liststickies: Lists all active sticky messages.
- /vote <user>: (Admin) Registers a vote against a user.
- /removevotes <user>: (Admin) Removes the most recent vote.
- /showvotes: (Admin) Lists all active votes.
- /purge <target> <scope> <limit>: Purge messages with confirmation.
- /mediaonly <action> <channel>: Sets media-only channels.
- /listmediaonly: Lists media-only channels.
- /dmroles <r1> <r2> <r3>: Sets the 3 DM roles.
- /dmreacts <e1> <e2>: Sets the 2 DM reaction emojis.
- /setdmmessage <0-5> <msg>: Sets DM preset messages.
- /listdmmessages: Lists all current DM preset messages.
- /dmreq <action> <channel>: Sets DM request channels.
- /listdmreq: Lists DM request settings.
- /setsleepvc <channel>: Sets the Sleep Voice Channel.
- /setcelebration <level> <msg>: Sets task completion messages.
- /sleep <target>: Moves user to Sleep VC.
- /task <amount>: Starts a task list.
- /setjail <channel>: (MamaBug) Sets the Jail VC.
- /timeout <user> <minutes>: (MamaBug) Puts a user in timeout.
- /lockout <start> <end> <repeat>: (MamaBug) User sets their own lockout.
- /lockoutview: (MamaBug) User views their lockout.
- /lockoutclear: (MamaBug) User clears their lockout.
- /adminclear <user>: (MamaBug) Admin clears a user's lockout.
- /help: Shows the help menu.

--- EVENTS ---
- on_ready: Startup sequence.
- on_raw_reaction_add: Handles ticket access, DM Request Logic, and Manual Role Removal.
- on_member_update: Handles auto-bans and ticket role assignment.
- on_voice_state_update: Handles jail logic (MamaBug).
- on_message: Handles Sticky, Music, Media Only, and DM Request logic.
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
from discord import app_commands
# Removed old scheduler imports to fix reliability
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
    
    # --- FEATURES ---
    "media_only_channels": [],
    "dm_req_channels": [],
    "dm_roles": [0, 0, 0], # [Role 1, Role 2, Role 3]
    "dm_reacts": ["👍", "👎"], # [React 1, React 2]
    "dm_messages": {
        "0": "{mention} Please include text with your mention to make a request.",
        "1": "Request Accepted!",
        "2": "Request Denied.",
        "3": "DM Request (Role 2) sent to {requested}.",
        "4": "DM Request (Role 3) sent to {requested}.",
        "5": "sorry they dont have dm roles yet :sob:, buggy's working on this"
    },
    
    # --- BETTER BUGGY FEATURES ---
    "sleep_vc_id": 0,
    "celebratory_messages": {
        "1": "Good start! Keep it up!",           # 0-24%
        "2": "You're making progress!",           # 25-49%
        "3": "Almost there, doing great!",        # 50-74%
        "4": "AMAZING! You finished the list!"    # 75-100%
    },

    # --- MAMABUG FEATURES ---
    "jail_vc_id": 0,
    "lockout_target_role_id": 0, # The role to remove/add (e.g. NSFW role)
    "time_zones": [], # List of {"guild_id": id, "role_id": id, "offset": int}
    "active_timeouts": {} # {user_id: {"remaining_seconds": X, "last_check": timestamp}}
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
    "dm_req_channels": list,
    "sleep_vc_id": int,
    "jail_vc_id": int,
    "lockout_target_role_id": int
}

CHANNEL_LISTS = ["nightly_channels", "link_safe_channels", "media_only_channels", "dm_req_channels"]
ROLE_LISTS = ["admin_role_id"]
CHANNEL_ID_KEYS = ["log_channel_id", "music_channel_id", "ticket_category_id", "sleep_vc_id", "jail_vc_id"]
ROLE_ID_KEYS = ["bad_role_to_ban_id", "ticket_access_role_id", "lockout_target_role_id"]

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
            return {"bot_config": [], "sticky_messages": [], "votes": [], "tasks": [], "user_lockouts": []}

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

    # --- TASK METHODS (BETTER BUGGY) ---
    async def load_tasks(self):
        return self.data.get("tasks", [])

    async def save_task(self, task_data):
        collection = self.data.get("tasks", [])
        # Update existing by removing old version first
        collection = [d for d in collection if d.get("message_id") != task_data["message_id"]]
        collection.append(task_data)
        self.data["tasks"] = collection
        self._save_to_file()

    async def delete_task(self, message_id):
        collection = self.data.get("tasks", [])
        collection = [d for d in collection if d.get("message_id") != message_id]
        self.data["tasks"] = collection
        self._save_to_file()
    
    async def find_task_by_user(self, user_id):
        collection = self.data.get("tasks", [])
        for doc in collection:
            if doc.get("user_id") == user_id:
                return doc
        return None

    # --- LOCKOUT METHODS (MAMABUG) ---
    async def get_user_lockout(self, user_id):
        collection = self.data.get("user_lockouts", [])
        for doc in collection:
            if doc.get("_id") == user_id:
                return doc
        return None

    async def save_user_lockout(self, user_id, data):
        collection = self.data.get("user_lockouts", [])
        # Remove existing
        collection = [d for d in collection if d.get("_id") != user_id]
        new_doc = {"_id": user_id}
        new_doc.update(data)
        collection.append(new_doc)
        self.data["user_lockouts"] = collection
        self._save_to_file()

    async def delete_user_lockout(self, user_id):
        collection = self.data.get("user_lockouts", [])
        collection = [d for d in collection if d.get("_id") != user_id]
        self.data["user_lockouts"] = collection
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
    
    # Ensure BetterBuggy settings exist
    if "sleep_vc_id" not in config: config["sleep_vc_id"] = 0
    if "celebratory_messages" not in config: config["celebratory_messages"] = DEFAULT_CONFIG["celebratory_messages"]

    # Ensure MamaBug settings exist
    if "jail_vc_id" not in config: config["jail_vc_id"] = 0
    if "lockout_target_role_id" not in config: config["lockout_target_role_id"] = 0
    if "time_zones" not in config: config["time_zones"] = []
    if "active_timeouts" not in config: config["active_timeouts"] = {}

    # Add message 5 if missing from old config
    if "5" not in config["dm_messages"]:
        config["dm_messages"]["5"] = DEFAULT_CONFIG["dm_messages"]["5"]

    if "_id" in config: del config["_id"]
    print("Configuration loaded.")

async def save_config_to_db():
    await db.save_config(config)

def is_admin_check(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator: return True
    return any(role.id in config['admin_role_id'] for role in interaction.user.roles)

def is_time_in_range(start_str, end_str, current_dt):
    current_time = current_dt.time()
    try:
        start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
        if start_time < end_time:
            return start_time <= current_time <= end_time
        else: 
            return current_time >= start_time or current_time <= end_time
    except:
        return False

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
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET: 
        print("⚠️ Spotify Client ID or Secret missing in secret_bot.py")
        return
    try:
        sp_auth = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
        spotify = Spotify(auth_manager=sp_auth)
        print("✅ Spotify Service Loaded.")
    except Exception as e: 
        print(f"❌ Failed to load Spotify: {e}")
        pass
    
    browser_path = os.path.join(BASE_DIR, 'browser.json')
    try:
        if os.path.exists(browser_path): ytmusic = YTMusic(browser_path)
    except: pass

async def process_spotify_link(url):
    if not spotify: return "Spotify service not loaded (Check ID/Secret)."
    if not ytmusic: return "YouTube Music service not loaded (browser.json missing)."
    if not youtube: return "YouTube API not loaded (License invalid)."
    if not config['playlist_id']: return "Playlist ID not set in config."

    match = re.search(r'(https?://[^\s]+)', url)
    clean_url = match.group(0) if match else url
    loop = asyncio.get_running_loop()
    
    try:
        # Get Track Info
        try:
            track = await loop.run_in_executor(None, spotify.track, clean_url)
        except Exception as e:
            return f"Spotify Error: Invalid link or API issue ({e})"

        search_query = f"{track['artists'][0]['name']} - {track['name']}"
        
        # Search YTM
        try:
            search_results = await loop.run_in_executor(None, lambda: ytmusic.search(search_query, "songs"))
        except Exception as e:
            return f"YTM Search Error: {e}"

        if not search_results: return f"Could not find '{search_query}' on YouTube Music."
        
        # Add to Playlist
        try:
            req = youtube.playlistItems().insert(
                part="snippet", 
                body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": search_results[0]['videoId']}}}
            )
            await loop.run_in_executor(None, req.execute)
            return True # Success
        except Exception as e:
            return f"YouTube API Error (Insert failed): {e}"

    except Exception as e: 
        return f"Unknown Error: {e}"

# --- TASK UI CLASS (BETTER BUGGY) ---
class TaskView(discord.ui.View):
    def __init__(self, user_id, total, state=None, message_id=None):
        super().__init__(timeout=None) # Persistent
        self.user_id = user_id
        self.total = total
        self.state = state if state else [0] * total
        self.message_id = message_id
        self.history = [] # Stack for Undo

    def get_emoji_bar(self):
        if self.total == 0: return ""
        cols, rows = 16, 2
        total_visual_blocks = cols * rows
        visual_state = []
        current_visual_count = 0
        for i in range(self.total):
            target_visual_count = int((i + 1) * total_visual_blocks / self.total)
            blocks_for_this_task = target_visual_count - current_visual_count
            visual_state.extend([self.state[i]] * blocks_for_this_task)
            current_visual_count += blocks_for_this_task
        if len(visual_state) < total_visual_blocks: visual_state.extend([0] * (total_visual_blocks - len(visual_state)))
        elif len(visual_state) > total_visual_blocks: visual_state = visual_state[:total_visual_blocks]

        SYM_DONE, SYM_SKIP, SYM_TODO = "🟩", "🟦", "⬜"
        row0, row1 = "-# ", "-# "
        for i in range(total_visual_blocks):
            val = visual_state[i]
            sym = SYM_DONE if val == 1 else (SYM_SKIP if val == 2 else SYM_TODO)
            if i % 2 == 0: row0 += sym
            else: row1 += sym
        return f"{row0}\n{row1}"

    async def update_message(self, interaction, finished=False, congratulation=None):
        completed_tasks = self.state.count(1) + self.state.count(2)
        content = f"<@{self.user_id}>'s tasks: {completed_tasks}/{self.total}\n{self.get_emoji_bar()}"
        if finished and congratulation:
            content += f"\n🎉 **{congratulation}**"
            view = None
        else: view = self

        if interaction: await interaction.response.edit_message(content=content, view=view)
        
        if finished: await db.delete_task(self.message_id)
        else: await self.update_db()

    async def update_db(self):
        if self.message_id:
            await db.save_task({
                "user_id": self.user_id,
                "message_id": self.message_id,
                "total": self.total,
                "state": self.state
            })

    def get_next_index(self):
        try: return self.state.index(0)
        except ValueError: return -1

    async def check_completion(self, interaction):
        if 0 not in self.state: await self.finish_logic(interaction)
        else: await self.update_message(interaction)

    async def finish_logic(self, interaction):
        self.state = [2 if x == 0 else x for x in self.state]
        greens = [x for x in self.state if x == 1]
        percent_complete = int((len(greens) / self.total) * 100) if self.total > 0 else 0
        
        msg_key = "1"
        if 25 <= percent_complete < 50: msg_key = "2"
        elif 50 <= percent_complete < 75: msg_key = "3"
        elif 75 <= percent_complete: msg_key = "4"
        
        celebration = config["celebratory_messages"].get(msg_key, "Good job!")
        await self.update_message(interaction, finished=True, congratulation=celebration)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="bb_done")
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        idx = self.get_next_index()
        if idx == -1: return await self.finish_logic(interaction)
        self.history.append((idx, 0))
        self.state[idx] = 1 
        await self.check_completion(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, custom_id="bb_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        idx = self.get_next_index()
        if idx == -1: return await self.finish_logic(interaction)
        self.history.append((idx, 0))
        self.state[idx] = 2 
        await self.check_completion(interaction)

    @discord.ui.button(label="Undo", style=discord.ButtonStyle.secondary, custom_id="bb_undo")
    async def undo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        if not self.history: return await interaction.response.send_message("Nothing to undo!", ephemeral=True)
        last_idx, last_val = self.history.pop()
        self.state[last_idx] = last_val
        await self.update_message(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="bb_finish")
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        await self.finish_logic(interaction)

# --- BOT SETUP ---
intents = discord.Intents.all()
# We keep command_prefix for fallback/debugging, but no prefix commands are registered.
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
# Use a simple UTC-5 offset for EST time
EST_TZ = datetime.timezone(datetime.timedelta(hours=-5))

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
                    # LIMIT=1000 is safer than None for reliability
                    deleted = await channel.purge(limit=1000, check=should_delete)
                    count += len(deleted)
            except Exception as e:
                 print(f"Purge Error: {e}")
        await send_log(f"**Purge Complete:** Deleted {count} messages.")
    finally: is_purging = False

async def check_token_validity_task():
    await load_youtube_service() 
    if youtube: await send_log("📅 **Daily Check:** YouTube License is Active & Valid.")
    else: await send_log("❌ **Daily Check:** YouTube License is EXPIRED or BROKEN.")

# New Robust Task Loop
@tasks.loop(minutes=1)
async def task_loop():
    # Get current time in EST
    now = datetime.datetime.now(EST_TZ)
    
    # 3:00 AM Purge
    if now.hour == 3 and now.minute == 0:
        await nightly_purge()
        
    # 4:00 AM Token Check
    if now.hour == 4 and now.minute == 0:
        await check_token_validity_task()

    # --- MAMABUG LOCKOUT LOGIC ---
    if not config.get('lockout_target_role_id'): return
    target_role_id = config['lockout_target_role_id']
    
    # Iterate through users with lockouts
    # Note: We can't iterate DB directly in loop, so we assume role-based checking from config['time_zones'] if used, 
    # OR we iterate members in guild. For simplicity + optimization, we'll iterate guilds -> members.
    
    current_utc = datetime.datetime.now(datetime.timezone.utc)
    
    for guild in bot.guilds:
        target_role = guild.get_role(target_role_id)
        if not target_role: continue
        
        # NOTE: iterating all members every minute can be heavy for huge servers. 
        # But for your personal bot usage, it's fine.
        for member in guild.members:
            if member.bot: continue
            
            user_data = await db.get_user_lockout(member.id)
            if not user_data or 'start' not in user_data: continue
            
            # Determine local time for user (simplified: assume EST or use offset if you had it)
            # Defaulting to EST for now as per your usual preference
            local_time = datetime.datetime.now(EST_TZ)
            
            should_be_locked = is_time_in_range(user_data['start'], user_data['end'], local_time)
            has_role = target_role in member.roles
            was_locked_by_bot = user_data.get('locked_by_bot', False)

            if should_be_locked and has_role:
                try: 
                    await member.remove_roles(target_role)
                    await db.save_user_lockout(member.id, {"start": user_data['start'], "end": user_data['end'], "repeat": user_data['repeat'], "locked_by_bot": True})
                    await send_log(f"🔒 **Lockout:** Removed role from {member.name}.")
                except: pass
            elif not should_be_locked and not has_role and was_locked_by_bot:
                try: 
                    await member.add_roles(target_role)
                    await db.save_user_lockout(member.id, {"start": user_data['start'], "end": user_data['end'], "repeat": user_data['repeat'], "locked_by_bot": False})
                    await send_log(f"🔓 **Lockout:** Restored role to {member.name}.")
                except: pass

@bot.event
async def on_ready():
    global db, sticky_data, vote_data
    try:
        db = DatabaseHandler(None, DB_NAME)
        await load_initial_config()
        sticky_data = await db.load_stickies()
        vote_data = await db.load_votes()
        
        # --- SYNC COMMANDS ---
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} Slash Commands.")
        
        # --- RESTORE TASKS ---
        active_tasks = await db.load_tasks()
        count = 0
        for doc in active_tasks:
            try:
                view = TaskView(
                    user_id=doc['user_id'], 
                    total=doc['total'], 
                    state=doc['state'], 
                    message_id=doc['message_id']
                )
                bot.add_view(view)
                count += 1
            except Exception as e:
                print(f"Failed to restore task view: {e}")
        print(f"✅ Restored {count} active tasks.")
        
    except Exception as e: print(f"DB Error or Sync Error: {e}")
    print(f"Hello! I am logged in as {bot.user}")
    
    if not check_manager_logs.is_running(): check_manager_logs.start()
    
    # Start the new task loop
    if not task_loop.is_running(): task_loop.start()
    
    await load_youtube_service()
    load_music_services()
    await send_log("Bot is online and ready (Slash Commands, Tasks, Jail & Lockout Active)!")

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
    if channel.id in config['dm_req_channels']:
        if str(payload.emoji) in config['dm_reacts']:
            try:
                message = await channel.fetch_message(payload.message_id)
                if member in message.mentions:
                    msg_index = -1
                    if str(payload.emoji) == config['dm_reacts'][0]: msg_index = "1"
                    elif str(payload.emoji) == config['dm_reacts'][1]: msg_index = "2"
                    
                    if msg_index != -1:
                        raw_msg = config['dm_messages'].get(msg_index, "")
                        formatted_msg = raw_msg.replace("{mention}", message.author.mention)\
                                               .replace("{requester}", message.author.mention)\
                                               .replace("{requested}", f"**{member.display_name}**")\
                                               .replace("{requested_nickname}", member.display_name)
                        await channel.send(formatted_msg)
                        
                        try:
                            for e in config['dm_reacts']:
                                await message.remove_reaction(e, bot.user)
                        except: pass

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

# --- MAMABUG JAIL LOGIC ---
@bot.event
async def on_voice_state_update(member, before, after):
    # Jail VC Check
    jail_vc_id = config.get('jail_vc_id')
    if not jail_vc_id: return

    user_id = str(member.id)
    active_timeouts = config.get('active_timeouts', {})
    
    if user_id not in active_timeouts: return

    timeout_data = active_timeouts[user_id]
    now = datetime.datetime.now().timestamp()

    # Entering Jail VC
    if after.channel and after.channel.id == jail_vc_id:
        timeout_data["last_check"] = now
        await save_config_to_db()
    
    # Leaving Jail VC
    elif (not after.channel or after.channel.id != jail_vc_id) and before.channel and before.channel.id == jail_vc_id:
        if timeout_data.get("last_check"):
            diff = now - timeout_data["last_check"]
            timeout_data["remaining_seconds"] = max(0, timeout_data["remaining_seconds"] - diff)
            timeout_data["last_check"] = None
            
            # Check if sentence is over (unlikely on leave, but possible if they left right at 0)
            if timeout_data["remaining_seconds"] <= 0:
                target_role_id = config.get('lockout_target_role_id')
                if target_role_id:
                    role = member.guild.get_role(target_role_id)
                    if role:
                        try:
                            await member.add_roles(role)
                            del active_timeouts[user_id]
                            await send_log(f"🔓 {member.mention} completed timeout and regained access!")
                        except Exception as e:
                            print(f"Failed to restore role: {e}")
            
            await save_config_to_db()

# --- SLASH COMMANDS ---

# --- AUTOCOMPLETE FUNCTIONS ---
async def settings_key_autocomplete(interaction: discord.Interaction, current: str) -> typing.List[app_commands.Choice[str]]:
    keys = list(SIMPLE_SETTINGS.keys())
    return [
        app_commands.Choice(name=key, value=key)
        for key in keys if current.lower() in key.lower()
    ][:25] # Limit to 25 choices

async def list_settings_key_autocomplete(interaction: discord.Interaction, current: str) -> typing.List[app_commands.Choice[str]]:
    keys = [k for k, v in SIMPLE_SETTINGS.items() if v == list]
    return [
        app_commands.Choice(name=key, value=key)
        for key in keys if current.lower() in key.lower()
    ][:25]

async def dm_message_index_autocomplete(interaction: discord.Interaction, current: str) -> typing.List[app_commands.Choice[str]]:
    indices = ["0", "1", "2", "3", "4", "5"]
    return [
        app_commands.Choice(name=index, value=index)
        for index in indices if current in index
    ]

@bot.tree.command(name="sync", description="Admin: Pulls changes from GitHub and restarts.")
@app_commands.check(is_admin_check)
async def sync(interaction: discord.Interaction):
    await interaction.response.send_message("♻️ **Syncing System...**\n1. Pulling code from GitHub...\n2. Restarting all bots (Give me 10 seconds!)")
    os.system("git pull")
    os.system("pkill -f main.py") 

@bot.tree.command(name="checkyoutube", description="Admin: Checks if YouTube API token is valid.")
@app_commands.check(is_admin_check)
async def checkyoutube(interaction: discord.Interaction):
    is_valid = await load_youtube_service() 
    if is_valid: await interaction.response.send_message(f"✅ **License Valid!**")
    else: await interaction.response.send_message("❌ **License Broken.**")

@bot.tree.command(name="setsetting", description="Admin: Sets a config value.")
@app_commands.check(is_admin_check)
@app_commands.autocomplete(key=settings_key_autocomplete)
async def setsetting(interaction: discord.Interaction, key: str, value: str):
    key = key.lower()
    if key not in SIMPLE_SETTINGS: return await interaction.response.send_message(f"❌ Invalid key.", ephemeral=True)
    try:
        if SIMPLE_SETTINGS[key] == list: new_val = [clean_id(i) for i in value.split()]
        elif SIMPLE_SETTINGS[key] == int: new_val = clean_id(value)
        else: new_val = value
        config[key] = new_val
        await save_config_to_db()
        await interaction.response.send_message(f"✅ Saved `{key}` as `{new_val}`.")
    except: await interaction.response.send_message("❌ Error: Check value.", ephemeral=True)

@bot.tree.command(name="addsetting", description="Admin: Adds items to a list config.")
@app_commands.check(is_admin_check)
@app_commands.autocomplete(key=list_settings_key_autocomplete)
async def addsetting(interaction: discord.Interaction, key: str, value: str):
    key = key.lower()
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list: return await interaction.response.send_message("❌ Not a list! Use `/setsetting`.", ephemeral=True)
    try:
        to_add = [clean_id(i) for i in value.split()]
        count = 0
        for item in to_add:
            if item not in config[key]: config[key].append(item); count += 1
        await save_config_to_db()
        await interaction.response.send_message(f"✅ Added {count} items.")
    except: await interaction.response.send_message("❌ Error.", ephemeral=True)

@bot.tree.command(name="removesetting", description="Admin: Removes items from a list config.")
@app_commands.check(is_admin_check)
@app_commands.autocomplete(key=list_settings_key_autocomplete)
async def removesetting(interaction: discord.Interaction, key: str, value: str):
    key = key.lower()
    if key not in SIMPLE_SETTINGS or SIMPLE_SETTINGS[key] != list: return await interaction.response.send_message("❌ Not a list!", ephemeral=True)
    try:
        to_remove = [clean_id(i) for i in value.split()]
        count = 0
        for item in to_remove:
            if item in config[key]: config[key].remove(item); count += 1
        await save_config_to_db()
        await interaction.response.send_message(f"✅ Removed {count} items.")
    except: await interaction.response.send_message("❌ Error.", ephemeral=True)

@bot.tree.command(name="showsettings", description="Admin: Shows all current config values.")
@app_commands.check(is_admin_check)
async def showsettings(interaction: discord.Interaction):
    text = "__**Bot Settings**__\n"
    for k, v in config.items():
        if k in SIMPLE_SETTINGS:
            disp = f"`{v}`"
            if k in CHANNEL_ID_KEYS and v != 0: disp = f"<#{v}>"
            elif k in CHANNEL_LISTS: disp = " ".join([f"<#{x}>" for x in v]) if v else "None"
            elif k in ROLE_ID_KEYS: disp = f"<@&{v}>"
            elif k in ROLE_LISTS: disp = " ".join([f"<@&{x}>" for x in v]) if v else "None"
            text += f"**{k}**: {disp}\n"
    await interaction.response.send_message(text[:2000]) # Safety limit

@bot.tree.command(name="refreshyoutube", description="Admin: Starts the OAuth flow to renew YouTube license.")
@app_commands.check(is_admin_check)
async def refreshyoutube(interaction: discord.Interaction):
    global auth_flow
    secret_path = os.path.join(BASE_DIR, 'client_secret.json')
    if not os.path.exists(secret_path): return await interaction.response.send_message("❌ Missing `client_secret.json`!", ephemeral=True)
    try:
        auth_flow = Flow.from_client_secrets_file(secret_path, scopes=['https://www.googleapis.com/auth/youtube'], redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        auth_url, _ = auth_flow.authorization_url(prompt='consent')
        await interaction.response.send_message(f"🔄 **Renewal Started!**\n1. Click: <{auth_url}>\n2. Type: `/entercode <code>`")
    except Exception as e: await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="entercode", description="Admin: Completes the YouTube renewal with the code.")
@app_commands.check(is_admin_check)
async def entercode(interaction: discord.Interaction, code: str):
    global auth_flow
    if not auth_flow: return await interaction.response.send_message("❌ Run `/refreshyoutube` first!", ephemeral=True)
    try:
        auth_flow.fetch_token(code=code)
        config['youtube_token_json'] = auth_flow.credentials.to_json()
        await save_config_to_db()
        await load_youtube_service() 
        await interaction.response.send_message("✅ **Success!** License renewed and saved to Database.")
    except Exception as e: await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="stick", description="Admin: Creates a sticky message in the current channel.")
@app_commands.check(is_admin_check)
async def stick(interaction: discord.Interaction, text: str):
    await interaction.response.send_message("✅ Sticky set.", ephemeral=True)
    msg = await interaction.channel.send(text)
    sticky_data[interaction.channel.id] = [text, msg.id, datetime.datetime.utcnow().timestamp()]
    await db.save_sticky(interaction.channel.id, text, msg.id, sticky_data[interaction.channel.id][2])

@bot.tree.command(name="unstick", description="Admin: Removes the sticky message in the current channel.")
@app_commands.check(is_admin_check)
async def unstick(interaction: discord.Interaction):
    if interaction.channel.id in sticky_data:
        sticky_data.pop(interaction.channel.id)
        await db.delete_sticky(interaction.channel.id)
        await interaction.response.send_message("✅ Removed.")
    else:
        await interaction.response.send_message("⚠️ No sticky here.", ephemeral=True)

@bot.tree.command(name="liststickies", description="Admin: Lists all active sticky messages.")
@app_commands.check(is_admin_check)
async def liststickies(interaction: discord.Interaction):
    if not sticky_data: return await interaction.response.send_message("❌ No stickies.", ephemeral=True)
    text = "**Active Stickies:**\n"
    for cid, data in sticky_data.items():
        text += f"<#{cid}>: {data[0][:50]}...\n"
    await interaction.response.send_message(text)

# --- PURGE COMMAND ---
@bot.tree.command(name="purge", description="Admin: Purge messages with confirmation.")
@app_commands.check(is_admin_check)
@app_commands.describe(target="User ID, 'nonmedia', or 'all'", limit="Number of messages to delete")
async def purge(interaction: discord.Interaction, target: str, limit: typing.Optional[int] = None, scope: typing.Optional[str] = None):
    # 1. Parse Target
    target_user = None
    target_mode = "all"
    
    if target.lower() == "all": target_mode = "all"
    elif target.lower() == "nonmedia": target_mode = "nonmedia"
    else:
        try: 
             target_user = interaction.guild.get_member(int(re.sub(r'[^0-9]', '', target)))
             if not target_user: raise ValueError
        except: return await interaction.response.send_message("❌ Invalid target. Use `@user`, `nonmedia`, or `all`.", ephemeral=True)

    # 2. Parse Scope
    channels = [interaction.channel]
    if scope:
        if scope.lower() == "server": channels = interaction.guild.text_channels
        # Simple ID lookup if provided
        elif scope.isdigit():
             c = interaction.guild.get_channel(int(scope))
             if c: channels = [c]

    # 3. Confirmation
    display_target = target_user.mention if target_user else target_mode.upper()
    display_limit = str(limit) if limit else "ALL"
    display_scope = f"{len(channels)} Channel(s)"
    
    await interaction.response.send_message(
        f"⚠️ **CONFIRM PURGE**\n"
        f"🎯 Target: {display_target}\n"
        f"📂 Scope: {display_scope}\n"
        f"🔢 Limit: {display_limit} messages\n\n"
        f"Type `yes` to confirm.",
        ephemeral=False 
    )
    
    def check(m): return m.author == interaction.user and m.channel == interaction.channel and m.content.lower() == "yes"
    try: 
        resp = await bot.wait_for("message", check=check, timeout=30)
        try: await resp.delete() 
        except: pass
    except: 
        return await interaction.edit_original_response(content="❌ Timed out.")

    # 4. Execution
    await interaction.edit_original_response(content=f"🧹 Purging...")
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
        except Exception as e: 
            print(f"Purge error in {c.name}: {e}")

    await interaction.edit_original_response(content=f"✅ Deleted {total} messages.")
    await asyncio.sleep(5)
    await interaction.delete_original_response()
    await send_log(f"🗑️ **Purge:** {interaction.user.name} deleted {total} messages ({target_mode}).")

@bot.tree.command(name="mediaonly", description="Admin: Sets media-only channels.")
@app_commands.check(is_admin_check)
@app_commands.choices(action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")])
async def mediaonly(interaction: discord.Interaction, action: app_commands.Choice[str], channel: discord.TextChannel):
    cid = channel.id
    if action.value == "add":
        if cid not in config['media_only_channels']:
            config['media_only_channels'].append(cid)
            await save_config_to_db()
            await interaction.response.send_message(f"✅ Channel <#{cid}> is now **Media Only**.")
        else: await interaction.response.send_message("⚠️ Already in list.", ephemeral=True)
    elif action.value == "remove":
        if cid in config['media_only_channels']:
            config['media_only_channels'].remove(cid)
            await save_config_to_db()
            await interaction.response.send_message(f"✅ Removed <#{cid}> from Media Only list.")
        else: await interaction.response.send_message("⚠️ Not in list.", ephemeral=True)

@bot.tree.command(name="listmediaonly", description="Admin: Lists media-only channels.")
@app_commands.check(is_admin_check)
async def listmediaonly(interaction: discord.Interaction):
    if not config['media_only_channels']: return await interaction.response.send_message("📂 No Media Only channels.", ephemeral=True)
    text = "📷 **Media Only Channels:**\n" + " ".join([f"<#{c}>" for c in config['media_only_channels']])
    await interaction.response.send_message(text)

@bot.tree.command(name="dmroles", description="Admin: Sets the 3 DM roles.")
@app_commands.check(is_admin_check)
async def dmroles(interaction: discord.Interaction, r1: discord.Role, r2: discord.Role, r3: discord.Role):
    config['dm_roles'] = [r1.id, r2.id, r3.id]
    await save_config_to_db()
    await interaction.response.send_message(f"✅ **DM Roles Set:**\n1. {r1.name}\n2. {r2.name}\n3. {r3.name}")

@bot.tree.command(name="dmreacts", description="Admin: Sets the 2 DM reaction emojis.")
@app_commands.check(is_admin_check)
async def dmreacts(interaction: discord.Interaction, e1: str, e2: str):
    config['dm_reacts'] = [e1, e2]
    await save_config_to_db()
    await interaction.response.send_message(f"✅ **DM Reacts Set:** {e1} (Accept) and {e2} (Deny)")

@bot.tree.command(name="setdmmessage", description="Admin: Sets DM preset messages.")
@app_commands.check(is_admin_check)
@app_commands.autocomplete(index=dm_message_index_autocomplete)
async def setdmmessage(interaction: discord.Interaction, index: str, message: str):
    if index not in ["0", "1", "2", "3", "4", "5"]: return await interaction.response.send_message("❌ Index must be 0-5.", ephemeral=True)
    config['dm_messages'][index] = message
    await save_config_to_db()
    await interaction.response.send_message(f"✅ **Message {index} Updated.**")

@bot.tree.command(name="listdmmessages", description="Admin: Lists all current DM preset messages.")
@app_commands.check(is_admin_check)
async def listdmmessages(interaction: discord.Interaction):
    text = "**📨 Current DM Messages:**\n"
    # Ensure order 0-5
    for i in range(6):
        key = str(i)
        if key in config['dm_messages']:
            text += f"**{key}:** {config['dm_messages'][key]}\n"
    await interaction.response.send_message(text)

@bot.tree.command(name="dmreq", description="Admin: Sets DM request channels.")
@app_commands.check(is_admin_check)
@app_commands.choices(action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")])
async def dmreq(interaction: discord.Interaction, action: app_commands.Choice[str], channel: discord.TextChannel):
    cid = channel.id
    if action.value == "add":
        if cid not in config['dm_req_channels']:
            config['dm_req_channels'].append(cid)
            await save_config_to_db()
            await interaction.response.send_message(f"✅ Channel <#{cid}> is now a **DM Request Channel**.")
        else: await interaction.response.send_message("⚠️ Already in list.", ephemeral=True)
    elif action.value == "remove":
        if cid in config['dm_req_channels']:
            config['dm_req_channels'].remove(cid)
            await save_config_to_db()
            await interaction.response.send_message(f"✅ Removed <#{cid}> from DM Request list.")
        else: await interaction.response.send_message("⚠️ Not in list.", ephemeral=True)

@bot.tree.command(name="listdmreq", description="Admin: Lists DM request settings.")
@app_commands.check(is_admin_check)
async def listdmreq(interaction: discord.Interaction):
    text = "**📨 DM Request Settings**\n"
    text += f"**Channels:** {' '.join([f'<#{c}>' for c in config['dm_req_channels']]) if config['dm_req_channels'] else 'None'}\n"
    text += f"**Roles:** <@&{config['dm_roles'][0]}>, <@&{config['dm_roles'][1]}>, <@&{config['dm_roles'][2]}>\n"
    text += f"**Reacts:** {config['dm_reacts'][0]} {config['dm_reacts'][1]}\n"
    await interaction.response.send_message(text)

@bot.tree.command(name="vote", description="Admin: Registers a vote against a user.")
@app_commands.check(is_admin_check)
async def vote(interaction: discord.Interaction, target: discord.User):
    user_id = target.id
    if user_id not in vote_data: vote_data[user_id] = []
    if interaction.user.id in vote_data[user_id]: pass
    vote_data[user_id].append(interaction.user.id)
    await db.save_vote(user_id, vote_data[user_id])
    await send_log(f"🗳️ **VOTE:** <@{interaction.user.id}> voted for <@{user_id}>. (Total: {len(vote_data[user_id])})")
    await interaction.response.send_message(f"✅ Voted for {target.mention}.", ephemeral=True)
    if len(vote_data[user_id]) >= 3:
        guild = interaction.guild
        member = guild.get_member(user_id)
        if member:
            try: await member.kick(reason="Received 3 votes from admins."); await send_log(f"🦶 **KICKED:** <@{user_id}>.")
            except: pass

@bot.tree.command(name="removevotes", description="Admin: Removes the most recent vote.")
@app_commands.check(is_admin_check)
async def removevotes(interaction: discord.Interaction, target: discord.User):
    user_id = target.id
    if user_id in vote_data and vote_data[user_id]:
        removed = vote_data[user_id].pop()
        await db.save_vote(user_id, vote_data[user_id])
        await interaction.response.send_message(f"✅ Removed one vote from <@{user_id}>.")
    else: await interaction.response.send_message(f"❌ No votes found.", ephemeral=True)

@bot.tree.command(name="showvotes", description="Admin: Lists all active votes.")
@app_commands.check(is_admin_check)
async def showvotes(interaction: discord.Interaction):
    if not vote_data: return await interaction.response.send_message("📝 No active votes.", ephemeral=True)
    text = "**Current Votes:**\n"
    for uid, voters in vote_data.items():
        if len(voters) > 0:
            voter_list = ", ".join([f"<@{v}>" for v in voters])
            text += f"• <@{uid}>: {len(voters)} votes ({voter_list})\n"
    await interaction.response.send_message(text)

# --- BETTER BUGGY COMMANDS ---

@bot.tree.command(name="setsleepvc", description="Admin: Sets the Sleep Voice Channel.")
@app_commands.check(is_admin_check)
async def setsleepvc(interaction: discord.Interaction, channel: discord.VoiceChannel):
    config['sleep_vc_id'] = channel.id
    await save_config_to_db()
    await interaction.response.send_message(f"✅ Sleep VC set to {channel.name}.")

@bot.tree.command(name="setcelebration", description="Admin: Sets task completion messages (Levels 1-4).")
@app_commands.check(is_admin_check)
@app_commands.choices(level=[
    app_commands.Choice(name="Level 1 (0-24%)", value="1"),
    app_commands.Choice(name="Level 2 (25-49%)", value="2"),
    app_commands.Choice(name="Level 3 (50-74%)", value="3"),
    app_commands.Choice(name="Level 4 (75-100%)", value="4")
])
async def setcelebration(interaction: discord.Interaction, level: app_commands.Choice[str], message: str):
    config['celebratory_messages'][level.value] = message
    await save_config_to_db()
    await interaction.response.send_message(f"✅ Celebration Level {level.value} updated.")

@bot.tree.command(name="sleep", description="Move yourself (or someone else, if Admin) to the Sleep VC.")
@app_commands.describe(target="User to move (Admin only)")
async def sleep(interaction: discord.Interaction, target: typing.Optional[discord.Member] = None):
    # Determine who to move
    member_to_move = interaction.user
    if target:
        # Check if caller is admin
        if interaction.user.guild_permissions.administrator or any(role.id in config['admin_role_id'] for role in interaction.user.roles):
            member_to_move = target
        else:
            return await interaction.response.send_message("🚫 **Access Denied:** Only Admins can move others!", ephemeral=True)

    # Check config
    if not config['sleep_vc_id']:
        return await interaction.response.send_message("❌ Sleep VC has not been set yet!", ephemeral=True)

    # Check voice state
    if not member_to_move.voice:
        return await interaction.response.send_message(f"❌ {member_to_move.display_name} is not in a voice channel!", ephemeral=True)

    sleep_channel = interaction.guild.get_channel(config['sleep_vc_id'])
    if not sleep_channel:
        return await interaction.response.send_message("❌ Sleep VC channel not found (ID might be wrong).", ephemeral=True)

    try:
        await member_to_move.move_to(sleep_channel)
        await interaction.response.send_message(f"💤 Moved {member_to_move.mention} to sleep.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to move members!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to move user: {e}", ephemeral=True)

@bot.tree.command(name="task", description="Start a new task list.")
@app_commands.describe(amount="Number of tasks (1-100)")
async def task(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("Please choose a number between 1 and 100, buggy!", ephemeral=True)

    existing = await db.find_task_by_user(interaction.user.id)
    if existing:
        return await interaction.response.send_message("You already have an active list! Please close it first.", ephemeral=True)

    view = TaskView(user_id=interaction.user.id, total=amount)
    await interaction.response.send_message(f"<@{interaction.user.id}>'s tasks: 0/{amount}\n{view.get_emoji_bar()}", view=view)
    
    # We need the message object to save the ID
    msg = await interaction.original_response()
    view.message_id = msg.id
    await view.update_db()

# --- MAMABUG COMMANDS ---

@bot.tree.command(name="setjail", description="Admin: Sets the Jail Voice Channel.")
@app_commands.check(is_admin_check)
async def setjail(interaction: discord.Interaction, channel: discord.VoiceChannel):
    config['jail_vc_id'] = channel.id
    await save_config_to_db()
    await interaction.response.send_message(f"✅ Jail VC set to {channel.name}.")

@bot.tree.command(name="timeout", description="Admin: Puts a user in jail.")
@app_commands.check(is_admin_check)
@app_commands.describe(minutes="Duration in minutes")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int):
    if not config['jail_vc_id']:
        return await interaction.response.send_message("❌ Jail VC not set. Use `/setjail`.", ephemeral=True)
    
    target_role_id = config.get('lockout_target_role_id')
    if not target_role_id:
        return await interaction.response.send_message("❌ Lockout Target Role not set (use `/setsetting lockout_target_role_id ...`).", ephemeral=True)

    role = interaction.guild.get_role(target_role_id)
    if not role: return await interaction.response.send_message("❌ Role not found.", ephemeral=True)

    try:
        await member.remove_roles(role)
        
        user_id = str(member.id)
        active_timeouts = config.get('active_timeouts', {})
        active_timeouts[user_id] = {
            "remaining_seconds": minutes * 60,
            "last_check": None
        }
        
        # If in jail already, start timer
        if member.voice and member.voice.channel and member.voice.channel.id == config['jail_vc_id']:
            active_timeouts[user_id]["last_check"] = datetime.datetime.now().timestamp()
            
        config['active_timeouts'] = active_timeouts
        await save_config_to_db()
        
        jail_channel = interaction.guild.get_channel(config['jail_vc_id'])
        await interaction.response.send_message(f"𐂺 {member.mention} jailed for **{minutes} mins**. Stay in {jail_channel.mention} to unlock!")
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="lockout", description="User: Set your own role lockout time.")
@app_commands.describe(start="HH:MM", end="HH:MM", repeat="daily/weekly")
async def lockout(interaction: discord.Interaction, start: str, end: str, repeat: str):
    try:
        datetime.datetime.strptime(start, "%H:%M")
        # Fix 4am bug logic from MamaBug
        e_obj = datetime.datetime.strptime(end, "%H:%M")
        if datetime.time(1, 0) <= e_obj.time() <= datetime.time(4, 0): end = "04:00"
    except:
        return await interaction.response.send_message("❌ Please use HH:MM format.", ephemeral=True)
        
    data = {"start": start, "end": end, "repeat": repeat.lower(), "locked_by_bot": False}
    await db.save_user_lockout(interaction.user.id, data)
    await interaction.response.send_message(f"✅ Lockout set for **{start}** to **{end}**!")

@bot.tree.command(name="lockoutview", description="User: View your lockout settings.")
async def lockoutview(interaction: discord.Interaction):
    user_data = await db.get_user_lockout(interaction.user.id)
    if not user_data or 'start' not in user_data:
        return await interaction.response.send_message("❌ You don't have a lockout set.", ephemeral=True)
    await interaction.response.send_message(f"📅 **Settings:**\nStart: {user_data['start']}\nEnd: {user_data['end']}\nRepeat: {user_data['repeat']}")

@bot.tree.command(name="lockoutclear", description="User: Clear your lockout settings.")
async def lockoutclear(interaction: discord.Interaction):
    user_data = await db.get_user_lockout(interaction.user.id)
    if not user_data: return await interaction.response.send_message("You don't have a lockout.", ephemeral=True)
    
    # Check if active
    if 'start' in user_data and is_time_in_range(user_data['start'], user_data['end'], datetime.datetime.now()):
         return await interaction.response.send_message("❌ You cannot clear your lockout while it is active!", ephemeral=True)
         
    await db.delete_user_lockout(interaction.user.id)
    await interaction.response.send_message("🗑️ Lockout cleared.")

@bot.tree.command(name="adminclear", description="Admin: Force clear a user's lockout.")
@app_commands.check(is_admin_check)
async def adminclear(interaction: discord.Interaction, target: discord.Member):
    await db.delete_user_lockout(target.id)
    await interaction.response.send_message(f"🧹 Cleared lockout for **{target.display_name}**.")

@bot.tree.command(name="help", description="Shows the help menu.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="BuggyBot Help", color=discord.Color.blue())
    embed.add_field(name="⚙️ Settings", value="`/setsetting`, `/addsetting`, `/removesetting`, `/showsettings`", inline=False)
    embed.add_field(name="📌 Sticky", value="`/stick`, `/unstick`, `/liststickies`", inline=False)
    embed.add_field(name="🧹 Purge", value="`/purge <user/nonmedia/all> <limit>`", inline=False)
    embed.add_field(name="📷 Media Only", value="`/mediaonly`, `/listmediaonly`", inline=False)
    embed.add_field(name="📨 DM Requests", value="`/dmreq`, `/dmroles`, `/setdmmessage`, `/listdmmessages`, `/listdmreq`", inline=False)
    embed.add_field(name="📝 Tasks & Sleep", value="`/task <amount>`, `/sleep [user]`\n`/setsleepvc`, `/setcelebration`", inline=False)
    embed.add_field(name="⛔ Lockout & Jail", value="`/lockout`, `/lockoutview`, `/lockoutclear`\n`/setjail`, `/timeout`", inline=False)
    embed.add_field(name="👑 Admin", value="`/vote`, `/removevotes`, `/showvotes`, `/adminclear`\n`/checkyoutube`, `/refreshyoutube`, `/entercode`", inline=False)
    embed.add_field(name="♻️ System", value="`/sync`", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.type == discord.MessageType.pins_add: 
        try: await message.delete(); return
        except: pass

    # Check for Admin Privileges (Bypass)
    is_admin_user = (
        message.author.guild_permissions.administrator or 
        any(role.id in config['admin_role_id'] for role in message.author.roles)
    )

    # --- 1. MEDIA ONLY CHANNELS ---
    if message.channel.id in config['media_only_channels']:
        if not is_admin_user:
            is_media = message.attachments or message.embeds or "http" in message.content
            
            if is_media:
                media_cooldowns[(message.author.id, message.channel.id)] = datetime.datetime.utcnow().timestamp()
            else:
                last_time = media_cooldowns.get((message.author.id, message.channel.id), 0)
                if datetime.datetime.utcnow().timestamp() - last_time > 300: # 5 mins
                    try: await message.delete()
                    except: pass
                    return

    # --- 2. DM REQUEST CHANNELS ---
    if message.channel.id in config['dm_req_channels']:
        
        # 1. STRICT PARSING
        cleaned_content = message.content.strip()
        match = re.match(r'^<@!?(\d+)>\s+(.+)', cleaned_content, re.DOTALL)
        
        valid_request = False
        target_member = None
        
        if match:
            user_id = int(match.group(1))
            target_member = message.guild.get_member(user_id)
            if target_member and not target_member.bot:
                valid_request = True
        
        # 2. ENFORCE RESTRICTIONS (Delete if bad)
        if not is_admin_user:
            if not valid_request:
                try:
                    await message.delete()
                    raw_msg = config['dm_messages'].get("0", "Error: No text.")
                    formatted_msg = raw_msg.replace("{mention}", message.author.mention).replace("{requester}", message.author.mention)
                    await message.channel.send(formatted_msg, delete_after=5)
                except: pass
                return
        
        # 3. FEATURE LOGIC
        if valid_request and target_member:
            target = target_member
            has_role_1 = any(r.id == config['dm_roles'][0] for r in target.roles)
            has_role_2 = any(r.id == config['dm_roles'][1] for r in target.roles)
            has_role_3 = any(r.id == config['dm_roles'][2] for r in target.roles)
            
            raw_msg = ""
            if has_role_1:
                try:
                    for e in config['dm_reacts']: await message.add_reaction(e)
                except: pass
            
            elif has_role_2:
                raw_msg = config['dm_messages'].get("3", "")
            elif has_role_3:
                raw_msg = config['dm_messages'].get("4", "")
            else:
                raw_msg = config['dm_messages'].get("5", "")
            
            if raw_msg:
                formatted_msg = raw_msg.replace("{mention}", message.author.mention)\
                                       .replace("{requester}", message.author.mention)\
                                       .replace("{requested}", f"**{target.display_name}**")\
                                       .replace("{requested_nickname}", target.display_name)
                await message.channel.send(formatted_msg)

    # --- 3. FIXED STICKY MESSAGES ---
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
            
    # --- 4. MUSIC LINKS ---
    if config['music_channel_id'] != 0 and message.channel.id == config['music_channel_id']:
        # Spotify Logic
        if "spotify.com" in message.content.lower():
             success_msg = await process_spotify_link(message.content)
             if success_msg is True: 
                 await message.add_reaction("🎵")
             else:
                 # It failed - Ping Admins
                 roles = [f"<@&{rid}>" for rid in config['admin_role_id']]
                 ping_str = " ".join(roles) if roles else "Admins"
                 await message.channel.send(f"⚠️ {ping_str} **Error:** Spotify link failed.\n`{success_msg}`")
        
        # YouTube Logic
        elif youtube:
            v_id = None
            if "v=" in message.content: v_id = message.content.split("v=")[1].split("&")[0]
            elif "youtu.be/" in message.content: v_id = message.content.split("youtu.be/")[1].split("?")[0]
            
            if v_id:
                try: 
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": config['playlist_id'], "resourceId": {"kind": "youtube#video", "videoId": v_id}}}).execute()
                    await message.add_reaction("🎵")
                except Exception as e:
                     # It failed - Ping Admins
                     roles = [f"<@&{rid}>" for rid in config['admin_role_id']]
                     ping_str = " ".join(roles) if roles else "Admins"
                     await message.channel.send(f"⚠️ {ping_str} **Error:** YouTube link from {message.author.mention} failed.\nError: `{e}`")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("🚫 **Access Denied:** You need to be an Admin to use this command!", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ **Error:** `{error}`", ephemeral=True)

bot.run(TOKEN)
