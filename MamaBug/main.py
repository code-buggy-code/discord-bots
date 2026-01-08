import sys
sys.path.append('..')
from secret_bot import TOKEN
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta, timezone, time
import json
import os

# --- FUNCTION LIST ---
# 1. DatabaseHandler Class: Handles all local JSON database interactions.
# 2. load_config(): Loads the global bot configuration from the database.
# 3. is_time_in_range(start, end, current): Helper for lockout time checking.
# 4. on_ready(): Startup sequence, initializes DB and tasks.
# 5. on_raw_reaction_add(): Handles manual role removal via reaction.
# 6. on_voice_state_update(): Handles jail logic (tracking time spent in voice).
# 7. check_lockout_times(): Background task for scheduled role lockouts.
# 8. help(): Custom help command.
# 9. myset(): Command for users to set their own lockout schedule.
# 10. myview(): Command for users to view their lockout settings.
# 11. myclear(): Command for users to delete their lockout settings.
# 12. adminclear(): Admin command to force clear a user lockout.
# 13. setjail(): Admin command to set the jail voice channel.
# 14. timeout(): Admin command to initiate a user timeout/jail sentence.

# --- 1. CONFIGURATION ---
PREFIX = "&"

DB_NAME = "RoleManagerDB"
CONFIG_COLLECTION = "bot_config"
USER_CONFIG_COLLECTION = "user_lockouts"

# --- 2. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
intents.voice_states = True # Needed for jail logic

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Global Config Cache
REACTION_REMOVALS = {} 
TIME_ZONES = [] 
LOCKOUT_CONFIG = {} 
JAIL_CONFIG = {
    "voice_channel_id": None,
    "active_timeouts": {} # {user_id: {"remaining_seconds": X, "last_check": timestamp}}
}

db = None

# --- 3. DATABASE CLASS ---
class DatabaseHandler:
    def __init__(self, uri, db_name):
        self.file_path = "database.json"
        self.data = self._load_from_file()

    def _load_from_file(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"bot_config": [], "sticky_messages": [], "user_lockouts": [], "jail_data": {}}

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

    async def get_user_lockout(self, user_id):
        collection = self.data.get("user_lockouts", [])
        for doc in collection:
            if doc.get("_id") == user_id:
                return doc
        return None

    async def save_user_lockout(self, user_id, data):
        collection = self.data.get("user_lockouts", [])
        existing = await self.get_user_lockout(user_id)
        new_doc = existing.copy() if existing else {"_id": user_id}
        new_doc.update(data)
        new_doc["_id"] = user_id 
        collection = [d for d in collection if d.get("_id") != user_id]
        collection.append(new_doc)
        self.data["user_lockouts"] = collection
        self._save_to_file()

    async def delete_user_lockout(self, user_id):
        collection = self.data.get("user_lockouts", [])
        collection = [d for d in collection if d.get("_id") != user_id]
        self.data["user_lockouts"] = collection
        self._save_to_file()

    async def load_data(self):
        return await self.load_config()

async def load_config():
    global REACTION_REMOVALS, TIME_ZONES, LOCKOUT_CONFIG, JAIL_CONFIG
    data = await db.load_data()
    saved_reactions = data.get('reaction_removals', {})
    REACTION_REMOVALS = {int(k): int(v) for k, v in saved_reactions.items()}
    TIME_ZONES = data.get('time_zones', [])
    LOCKOUT_CONFIG = data.get('lockout_config', {})
    
    # Load Jail Data
    jail_data = db.data.get("jail_data", {})
    JAIL_CONFIG["voice_channel_id"] = jail_data.get("voice_channel_id")
    JAIL_CONFIG["active_timeouts"] = jail_data.get("active_timeouts", {})
    
    print("✅ Configuration loaded!")

def is_time_in_range(start_str, end_str, current_dt):
    current_time = current_dt.time()
    start_time = datetime.strptime(start_str, "%H:%M").time()
    end_time = datetime.strptime(end_str, "%H:%M").time()
    if start_time < end_time:
        return start_time <= current_time <= end_time
    else: 
        return current_time >= start_time or current_time <= end_time

# --- 5. EVENTS ---

@bot.event
async def on_ready():
    global db
    db = DatabaseHandler("mongodb://localhost:27017", DB_NAME)
    await load_config()
    check_lockout_times.start()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id == 1447651143324012717:
        guild = bot.get_guild(payload.guild_id)
        if not guild: return
        role = guild.get_role(1434622680614834206)
        member = payload.member
        if role and member and role in member.roles:
            try:
                await member.remove_roles(role)
                await db.save_user_lockout(member.id, {"locked_by_bot": False})
                log_channel = bot.get_channel(1434622477660717056)
                if log_channel:
                    await log_channel.send(f"<@&1437836167927042289> I removed the role from {member.mention} (Manual Reaction)!")
            except Exception as e:
                print(f"Failed to remove role: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Handles time tracking for jailed users."""
    user_id = str(member.id)
    if user_id not in JAIL_CONFIG["active_timeouts"]:
        return

    jail_vc_id = JAIL_CONFIG["voice_channel_id"]
    if not jail_vc_id:
        return

    now = datetime.now().timestamp()
    timeout_data = JAIL_CONFIG["active_timeouts"][user_id]

    # Entering Jail VC
    if after.channel and after.channel.id == jail_vc_id:
        timeout_data["last_check"] = now
    
    # Leaving Jail VC
    elif (not after.channel or after.channel.id != jail_vc_id) and before.channel and before.channel.id == jail_vc_id:
        if timeout_data.get("last_check"):
            diff = now - timeout_data["last_check"]
            timeout_data["remaining_seconds"] = max(0, timeout_data["remaining_seconds"] - diff)
            timeout_data["last_check"] = None
            
            # Save progress
            db.data["jail_data"]["active_timeouts"] = JAIL_CONFIG["active_timeouts"]
            db._save_to_file()

            # Check if sentence is over
            if timeout_data["remaining_seconds"] <= 0:
                target_role_id = LOCKOUT_CONFIG.get('target_role_id')
                if target_role_id:
                    role = member.guild.get_role(target_role_id)
                    if role:
                        try:
                            await member.add_roles(role)
                            del JAIL_CONFIG["active_timeouts"][user_id]
                            db.data["jail_data"]["active_timeouts"] = JAIL_CONFIG["active_timeouts"]
                            db._save_to_file()
                            
                            log_channel = bot.get_channel(1434622477660717056)
                            if log_channel:
                                await log_channel.send(f"🔓 {member.mention} has served their sentence in jail and regained NSFW access!")
                        except Exception as e:
                            print(f"Failed to restore role to jailed user: {e}")

# --- 6. BACKGROUND TASK ---

@tasks.loop(minutes=1)
async def check_lockout_times():
    # Jail Logic Update (Tick while they are in VC)
    now = datetime.now().timestamp()
    jail_vc_id = JAIL_CONFIG["voice_channel_id"]
    
    if jail_vc_id:
        for uid, data in list(JAIL_CONFIG["active_timeouts"].items()):
            member_id = int(uid)
            # Find the member in guilds
            for guild in bot.guilds:
                member = guild.get_member(member_id)
                if member and member.voice and member.voice.channel and member.voice.channel.id == jail_vc_id:
                    if data.get("last_check"):
                        diff = now - data["last_check"]
                        data["remaining_seconds"] = max(0, data["remaining_seconds"] - diff)
                        data["last_check"] = now
                        
                        if data["remaining_seconds"] <= 0:
                            target_role_id = LOCKOUT_CONFIG.get('target_role_id')
                            if target_role_id:
                                role = guild.get_role(target_role_id)
                                if role:
                                    try:
                                        await member.add_roles(role)
                                        del JAIL_CONFIG["active_timeouts"][uid]
                                        log_channel = bot.get_channel(1434622477660717056)
                                        if log_channel:
                                            await log_channel.send(f"🔓 {member.mention} has served their sentence in jail and regained NSFW access!")
                                    except: pass
                    else:
                        data["last_check"] = now
            
        db.data["jail_data"]["active_timeouts"] = JAIL_CONFIG["active_timeouts"]
        db._save_to_file()

    # Original Lockout Logic
    if not LOCKOUT_CONFIG: return 
    current_utc = datetime.now(timezone.utc)
    target_role_id = LOCKOUT_CONFIG.get('target_role_id')
    if not target_role_id: return

    for zone_config in TIME_ZONES:
        guild = bot.get_guild(zone_config['guild_id'])
        if not guild: continue
        target_role = guild.get_role(target_role_id)
        tz_role = guild.get_role(zone_config['role_id'])
        if not tz_role or not target_role: continue
        offset = zone_config['offset']
        local_time = current_utc + timedelta(hours=offset)

        for member in tz_role.members:
            user_data = await db.get_user_lockout(member.id)
            if not user_data or 'start' not in user_data: continue
            should_be_locked = is_time_in_range(user_data['start'], user_data['end'], local_time)
            has_role = target_role in member.roles
            was_locked_by_bot = user_data.get('locked_by_bot', False)

            if should_be_locked and has_role:
                try: 
                    await member.remove_roles(target_role)
                    await db.save_user_lockout(member.id, {"locked_by_bot": True})
                except: pass
            elif not should_be_locked and not has_role and was_locked_by_bot:
                try: 
                    await member.add_roles(target_role)
                    await db.save_user_lockout(member.id, {"locked_by_bot": False})
                except: pass

@check_lockout_times.before_loop
async def before_check():
    await bot.wait_until_ready()

# --- 7. COMMANDS ---

@bot.command()
async def help(ctx):
    is_admin = ctx.author.guild_permissions.administrator
    embed = discord.Embed(color=discord.Color.green(), title="MamaBug Help")
    if is_admin:
        embed.add_field(name="Admin Commands", value=(
            f"`{PREFIX}addzone` | `{PREFIX}listzones`\n"
            f"`{PREFIX}adminclear <@user>` - Force clear lockout\n"
            f"`{PREFIX}setjail <voice_channel_id>` - Set jail VC\n"
            f"`{PREFIX}timeout <@user> <minutes>` - Jail a user"
        ), inline=False)
    embed.add_field(name="User Commands", value=(
        f"`{PREFIX}myset <HH:MM> <HH:MM> <repeat>`\n"
        f"`{PREFIX}myview` | `{PREFIX}myclear`"
    ), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def myset(ctx, start: str, end: str, repeat: str):
    try:
        datetime.strptime(start, "%H:%M")
        e_obj = datetime.strptime(end, "%H:%M")
        if time(1, 0) <= e_obj.time() <= time(4, 0): end = "04:00"
    except:
        await ctx.send("❌ Please use HH:MM format.")
        return
    data = {"start": start, "end": end, "repeat": repeat.lower(), "locked_by_bot": False}
    await db.save_user_lockout(ctx.author.id, data)
    await ctx.send(f"✅ Lockout set for **{start}** to **{end}**!")

@bot.command()
async def myview(ctx):
    user_data = await db.get_user_lockout(ctx.author.id)
    if not user_data or 'start' not in user_data:
        await ctx.send("❌ You don't have a custom lockout set, buggy!")
        return
    await ctx.send(f"📅 **Your Lockout Settings:**\n⏰ **Start:** {user_data['start']}\n⏰ **End:** {user_data['end']}\n🔁 **Repeat:** {user_data['repeat']}")

@bot.command()
async def myclear(ctx):
    user_data = await db.get_user_lockout(ctx.author.id)
    if not user_data: return await ctx.send("You don't have a custom lockout set.")
    if 'start' in user_data and is_time_in_range(user_data['start'], user_data['end'], datetime.now()):
         return await ctx.send("❌ You cannot clear your lockout while it is active!")
    await db.delete_user_lockout(ctx.author.id)
    await ctx.send("🗑️ Your custom lockout has been cleared.")

@bot.command()
@commands.has_permissions(administrator=True)
async def adminclear(ctx, member: discord.Member):
    await db.delete_user_lockout(member.id)
    await ctx.send(f"🧹 Admin Force: Cleared lockout for **{member.display_name}**.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setjail(ctx, channel_id: int):
    """Sets the voice channel users must stay in for timeout."""
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.VoiceChannel):
        return await ctx.send("❌ Please provide a valid Voice Channel ID.")
    
    JAIL_CONFIG["voice_channel_id"] = channel_id
    db.data["jail_data"] = {"voice_channel_id": channel_id, "active_timeouts": JAIL_CONFIG["active_timeouts"]}
    db._save_to_file()
    await ctx.send(f"✅ Jail voice channel set to **{channel.name}**.")

@bot.command()
@commands.has_permissions(administrator=True)
async def timeout(ctx, member: discord.Member, minutes: int):
    """Removes NSFW access until the user stays in the jail VC for specified minutes."""
    target_role_id = LOCKOUT_CONFIG.get('target_role_id')
    if not target_role_id:
        return await ctx.send("❌ No NSFW target role configured in lockout settings.")

    role = ctx.guild.get_role(target_role_id)
    if not role:
        return await ctx.send("❌ Could not find the configured NSFW role.")

    if not JAIL_CONFIG["voice_channel_id"]:
        return await ctx.send(f"❌ Jail voice channel not set. Use `{PREFIX}setjail <id>` first.")

    try:
        # Remove role
        await member.remove_roles(role)
        
        # Add to timeout tracker
        user_id = str(member.id)
        JAIL_CONFIG["active_timeouts"][user_id] = {
            "remaining_seconds": minutes * 60,
            "last_check": None
        }
        
        # If already in the jail VC, start timer immediately
        if member.voice and member.voice.channel and member.voice.channel.id == JAIL_CONFIG["voice_channel_id"]:
            JAIL_CONFIG["active_timeouts"][user_id]["last_check"] = datetime.now().timestamp()

        db.data["jail_data"]["active_timeouts"] = JAIL_CONFIG["active_timeouts"]
        db._save_to_file()

        jail_channel = bot.get_channel(JAIL_CONFIG["voice_channel_id"])
        await ctx.send(f"⚖️ {member.mention} has been jailed for **{minutes} minutes**. They must stay in {jail_channel.mention} to regain NSFW access.")
        
    except Exception as e:
        await ctx.send(f"❌ Failed to jail user: {e}")

if TOKEN:
    bot.run(TOKEN)
