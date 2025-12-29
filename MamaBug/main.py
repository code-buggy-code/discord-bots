import sys
sys.path.append('..')
from secret_bot import TOKEN
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta, timezone, time
import json
import os

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

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Global Config Cache
REACTION_REMOVALS = {} 
TIME_ZONES = [] 
LOCKOUT_CONFIG = {} 

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
            return {"bot_config": [], "sticky_messages": [], "user_lockouts": []}

    def _save_to_file(self):
        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=4, default=str)

    async def load_config(self):
        collection = self.data.get("bot_config", [])
        for doc in collection:
            if doc.get("_id") == "config":
                return doc
        return {}

    # --- USER LOCKOUT METHODS ---
    async def get_user_lockout(self, user_id):
        collection = self.data.get("user_lockouts", [])
        for doc in collection:
            if doc.get("_id") == user_id:
                return doc
        return None

    async def save_user_lockout(self, user_id, data):
        collection = self.data.get("user_lockouts", [])
        existing = await self.get_user_lockout(user_id)
        
        # Merge new data with existing (preserves 'locked_by_bot' flag)
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
    global REACTION_REMOVALS, TIME_ZONES, LOCKOUT_CONFIG
    data = await db.load_data()
    saved_reactions = data.get('reaction_removals', {})
    REACTION_REMOVALS = {int(k): int(v) for k, v in saved_reactions.items()}
    TIME_ZONES = data.get('time_zones', [])
    LOCKOUT_CONFIG = data.get('lockout_config', {})
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
    # URI is dummy now since we use local file
    db = DatabaseHandler("mongodb://localhost:27017", DB_NAME)
    await load_config()
    check_lockout_times.start()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_raw_reaction_add(payload):
    # Check if the reaction is on the specific message
    if payload.message_id == 1447651143324012717:
        guild = bot.get_guild(payload.guild_id)
        if not guild: return
        
        # The role to remove
        role = guild.get_role(1434622680614834206)
        member = payload.member
        
        # Remove the role if they have it
        if role and member and role in member.roles:
            try:
                await member.remove_roles(role)
                
                # --- CRITICAL FIX START ---
                # We mark 'locked_by_bot' as False.
                # This tells the scheduler: "The user did this manually. Do not auto-restore."
                await db.save_user_lockout(member.id, {"locked_by_bot": False})
                # --- CRITICAL FIX END ---

                log_channel = bot.get_channel(1434622477660717056)
                if log_channel:
                    await log_channel.send(f"<@&1437836167927042289> I removed the role from {member.mention} (Manual Reaction)!")
            except Exception as e:
                print(f"Failed to remove role: {e}")

# --- 6. BACKGROUND TASK ---

@tasks.loop(minutes=1)
async def check_lockout_times():
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
            if not user_data: continue

            should_be_locked = is_time_in_range(user_data['start'], user_data['end'], local_time)
            has_role = target_role in member.roles
            
            # Check the flag!
            was_locked_by_bot = user_data.get('locked_by_bot', False)

            # CASE 1: TIME TO SLEEP (Lock them out)
            if should_be_locked and has_role:
                try: 
                    await member.remove_roles(target_role)
                    # Mark that WE took it for the schedule
                    await db.save_user_lockout(member.id, {"locked_by_bot": True})
                    print(f"🔒 Locked out {member.display_name}")
                except Exception as e: 
                    print(f"Failed to lock {member.display_name}: {e}")

            # CASE 2: TIME TO WAKE UP (Give it back... maybe)
            elif not should_be_locked and not has_role:
                # ONLY give it back if WE were the ones who took it via schedule!
                if was_locked_by_bot:
                    try: 
                        await member.add_roles(target_role)
                        # Reset the flag so we don't spam add it
                        await db.save_user_lockout(member.id, {"locked_by_bot": False})
                        print(f"🔓 Unlocked {member.display_name}")
                    except Exception as e: 
                        print(f"Failed to unlock {member.display_name}: {e}")
                else:
                    # If locked_by_bot is False, they removed it themselves (via reaction).
                    # Do NOT add it back.
                    pass

@check_lockout_times.before_loop
async def before_check():
    await bot.wait_until_ready()

# --- 7. COMMANDS ---

@bot.command()
async def help(ctx):
    is_admin = ctx.author.guild_permissions.administrator
    embed = discord.Embed(color=discord.Color.green())
    if is_admin:
        embed.add_field(name="Admin Commands", value=(
            f"`{PREFIX}addzone` | `{PREFIX}listzones`\n"
            f"`{PREFIX}adminclear <@user>` - Force clear a user's lockout"
        ), inline=False)
        embed.add_field(name="User Commands", value=(
            f"`{PREFIX}myset <HH:MM> <HH:MM> <daily/weekly/none>`\n"
            f"`{PREFIX}myview` | `{PREFIX}myclear`"
        ), inline=False)
    else:
        embed.description = (
            f"`{PREFIX}myset <HH:MM> <HH:MM> <daily/weekly/none>` - Create lockout\n"
            f"`{PREFIX}myview` - View your settings\n"
            f"`{PREFIX}myclear` - Delete your lockout"
        )
    await ctx.send(embed=embed)

@bot.command()
async def myset(ctx, start: str, end: str, repeat: str):
    try:
        s_obj = datetime.strptime(start, "%H:%M")
        e_obj = datetime.strptime(end, "%H:%M")
        if time(1, 0) <= e_obj.time() <= time(4, 0):
            end = "04:00"
    except:
        await ctx.send("❌ Please use HH:MM format.")
        return

    # Initialize locked_by_bot as False
    data = {"start": start, "end": end, "repeat": repeat.lower(), "locked_by_bot": False}
    await db.save_user_lockout(ctx.author.id, data)
    await ctx.send(f"✅ Lockout set for **{start}** to **{end}**!")

@bot.command()
async def myclear(ctx):
    user_data = await db.get_user_lockout(ctx.author.id)
    if not user_data:
        await ctx.send("You don't have a custom lockout set.")
        return

    now = datetime.now()
    if is_time_in_range(user_data['start'], user_data['end'], now):
         await ctx.send("❌ You cannot clear your lockout while it is active!")
         return

    await db.delete_user_lockout(ctx.author.id)
    await ctx.send("🗑️ Your custom lockout has been cleared.")

@bot.command()
@commands.has_permissions(administrator=True)
async def adminclear(ctx, member: discord.Member):
    await db.delete_user_lockout(member.id)
    await ctx.send(f"🧹 Admin Force: Cleared lockout for **{member.display_name}**.")

if TOKEN:
    bot.run(TOKEN)
