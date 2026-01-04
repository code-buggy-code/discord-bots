import sys
sys.path.append('..')
from secret_bot import TOKEN
import discord
from discord.ext import commands, tasks
import json
import os
import time
from datetime import datetime, timezone 
import asyncio 

# --- FUNCTION LIST ---
# To ensure nothing is lost, here is the list of all functions in this bot:
# 1. DatabaseHandler Class:
#    - __init__, _load_from_file, _save_to_file
#    - load_config, save_config, load_stickies, save_sticky, delete_sticky
#    - update_user_points, get_all_group_points, clear_points_by_group
# 2. Configuration:
#    - load_initial_config, save_config_to_db
# 3. Utility:
#    - add_points_to_cache, is_category_tracked, _create_leaderboard_embed
#    - refresh_group_leaderboard, check_admin_perms, is_user_admin (NEW)
# 4. Events:
#    - on_ready, on_message, on_message_delete, on_reaction_add, on_voice_state_update
# 5. Tasks:
#    - voice_time_checker, point_saver
# 6. Commands:
#    - set_log_channel, set_vc_role, manage_admin_roles (UPDATED), set_permanent_leaderboard
#    - clear_permanent_leaderboard, clear_group_points, show_leaderboard
#    - rename_group, track_category, untrack_category, award_points, remove_points
#    - show_points, show_settings_cmd, set_points

# --- 1. CONFIGURATION SETTINGS ---
PREFIX = "^" 

# Database configuration
DB_NAME = "LeaderboardDB"

# --- 2. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# --- 3. DATA AND POINT STRUCTURES & GLOBALS ---
DEFAULT_POINT_VALUES = {
    'message': 1,
    'attachment': 2,
    'voice_interval': 1,
    'reaction_add': 1,
    'reaction_receive': 2
}

DEFAULT_GROUPS = {
    "Group1": {"name": "Meowzers", "categories": []},
    "Group2": {"name": "Arfers", "categories": []},
    "Group3": {"name": "Buggies", "categories": []}
}

# Global in-memory variables
POINT_VALUES = DEFAULT_POINT_VALUES.copy()
LEADERBOARD_GROUPS = DEFAULT_GROUPS.copy() 
VOICE_TRACKER = {} 
POINT_CACHE = {}         
LEADERBOARD_CACHE = {}   
PERMANENT_LEADERBOARDS = {} 

# Globals for Roles & Logging
VC_NOTIFY_ROLE_ID = None
ADMIN_ROLE_IDS = [] # Changed to a list to support multiple roles
VC_ACTIVE_STATE = {} 
LOG_CHANNEL_ID = None 

# Global DB handler instance
db = None


# --- 4. DATABASE HANDLER (LOCAL FILE VERSION) ---
class DatabaseHandler:
    def __init__(self, uri, db_name):
        self.file_path = "database.json"
        self.data = self._load_from_file()

    def _load_from_file(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"bot_config": [], "sticky_messages": [], "user_points": []}

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

    async def update_user_points(self, guild_id, group_key, user_id, points):
        user_id = str(user_id)
        guild_id = str(guild_id)
        collection = self.data.get("user_points", [])
        
        found = False
        for doc in collection:
            if doc.get("guild_id") == guild_id and \
               doc.get("group_key") == group_key and \
               doc.get("user_id") == user_id:
                doc["points"] = int(doc.get("points", 0)) + int(points)
                found = True
                break
        
        if not found:
            new_doc = {
                "guild_id": guild_id,
                "group_key": group_key,
                "user_id": user_id,
                "points": int(points)
            }
            collection.append(new_doc)
            
        self.data["user_points"] = collection
        self._save_to_file()

    async def get_all_group_points(self, guild_id, group_key):
        guild_id = str(guild_id)
        collection = self.data.get("user_points", [])
        results = {}
        for doc in collection:
            if doc.get("guild_id") == guild_id and doc.get("group_key") == group_key:
                results[doc["user_id"]] = doc.get("points", 0)
        return results

    async def clear_points_by_group(self, guild_id, group_key):
        guild_id = str(guild_id)
        collection = self.data.get("user_points", [])
        initial_count = len(collection)
        
        new_collection = [
            doc for doc in collection 
            if not (doc.get("guild_id") == guild_id and doc.get("group_key") == group_key)
        ]
        
        self.data["user_points"] = new_collection
        self._save_to_file()
        return initial_count - len(new_collection)

# --- 5. CONFIGURATION LOADING ---
async def load_initial_config():
    """Loads initial configuration from MongoDB."""
    global POINT_VALUES, LEADERBOARD_GROUPS, LEADERBOARD_CACHE, PERMANENT_LEADERBOARDS, VC_NOTIFY_ROLE_ID, LOG_CHANNEL_ID, ADMIN_ROLE_IDS
    
    config = await db.load_config()

    # Load POINT_VALUES
    loaded_points = config.get('POINT_VALUES', DEFAULT_POINT_VALUES)
    POINT_VALUES.update(DEFAULT_POINT_VALUES)
    POINT_VALUES.update(loaded_points)
    
    # Load GROUPS
    groups_config = config.get('LEADERBOARD_GROUPS', DEFAULT_GROUPS)
    temp_groups = {key: data for key, data in groups_config.items() if key in DEFAULT_GROUPS} 
    LEADERBOARD_GROUPS.update(DEFAULT_GROUPS.copy())
    LEADERBOARD_GROUPS.update(temp_groups)
    
    # Load CACHE and Permanent Leaderboard
    LEADERBOARD_CACHE = config.get('LEADERBOARD_CACHE', {})
    PERMANENT_LEADERBOARDS = config.get('PERMANENT_LEADERBOARDS', {})

    # Load Roles and Channels
    VC_NOTIFY_ROLE_ID = config.get('VC_NOTIFY_ROLE_ID', None)
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID', None)
    
    # Load Admin Role IDs (Handle legacy single ID or new list)
    admin_data = config.get('ADMIN_ROLE_IDS', None)
    if admin_data is None:
        # Check for old key just in case
        old_id = config.get('ADMIN_ROLE_ID', None)
        ADMIN_ROLE_IDS = [old_id] if old_id else []
    elif isinstance(admin_data, list):
        ADMIN_ROLE_IDS = admin_data
    else:
        ADMIN_ROLE_IDS = []
    
    print("Configuration loaded from MongoDB.")

async def save_config_to_db():
    """Saves all current bot configuration to MongoDB."""
    config = {
        'POINT_VALUES': POINT_VALUES,
        'LEADERBOARD_GROUPS': LEADERBOARD_GROUPS,
        'LEADERBOARD_CACHE': LEADERBOARD_CACHE,
        'PERMANENT_LEADERBOARDS': PERMANENT_LEADERBOARDS,
        'VC_NOTIFY_ROLE_ID': VC_NOTIFY_ROLE_ID,
        'LOG_CHANNEL_ID': LOG_CHANNEL_ID,
        'ADMIN_ROLE_IDS': ADMIN_ROLE_IDS 
    }
    await db.save_config(config)

# --- 6. UTILITY FUNCTIONS (In-Memory Cache) ---

def add_points_to_cache(user_id, guild_id, group_key, points):
    """Adds points to the in-memory cache for periodic saving. Uses integers only."""
    user_id = str(user_id)
    guild_id = str(guild_id)
    
    if guild_id not in POINT_CACHE:
        POINT_CACHE[guild_id] = {}
    if group_key not in POINT_CACHE[guild_id]:
        POINT_CACHE[guild_id][group_key] = {}
        
    current = POINT_CACHE[guild_id][group_key].get(user_id, 0)
    POINT_CACHE[guild_id][group_key][user_id] = current + int(points) 


def is_category_tracked(channel):
    """Checks if a channel's category is in a tracked group and returns the group key (e.g., 'Group1')."""
    if not channel.category:
        return None
    cat_id = channel.category.id
    
    for group_key, group_data in LEADERBOARD_GROUPS.items():
        if cat_id in group_data['categories']:
            return group_key
    return None

async def _create_leaderboard_embed(guild, group_key):
    """Helper function to create the leaderboard embed based on the cache."""
    guild_id = str(guild.id)
    group_name = LEADERBOARD_GROUPS.get(group_key, {}).get('name', 'Unknown Group')
    cache_data = LEADERBOARD_CACHE.get(guild_id, {}).get(group_key, {})
    top_users = cache_data.get('top_users', [])
    updated_time_unix = cache_data.get('updated', 'N/A')

    embed = discord.Embed(
        title=f"🏆 {guild.name} - {group_name}",
        color=discord.Color.gold()
    )
    
    footer_timestamp = f"N/A" if updated_time_unix == 'N/A' else f"<t:{updated_time_unix}:f>"
    
    leaderboard_text = f"**As of** {footer_timestamp}\n\n"
    
    if not top_users:
        embed.description = leaderboard_text + "🥺 No points recorded yet."
        embed.set_footer(text=f"Refreshes every 5 minutes")
        return embed
        
    for rank, (user_id_str, points) in enumerate(top_users, 1):
        try:
            user = bot.get_user(int(user_id_str)) or await bot.fetch_user(int(user_id_str))
            display_name = user.display_name if user else "[User Left]" 
            emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**#{rank}**")
            leaderboard_text += f"{emoji} **{display_name}**: {int(points)} Points\n"
        except discord.NotFound:
            leaderboard_text += f"**#{rank}** **[User Left]**: {int(points)} Points\n"

    embed.description = leaderboard_text
    embed.set_footer(text=f"Refreshes every 5 minutes")
    return embed

async def refresh_group_leaderboard(guild, group_key):
    """Refreshes the leaderboard cache and permanent message for a specific group immediately."""
    guild_id = str(guild.id)
    
    # 1. Fetch latest data from DB
    leader_data = await db.get_all_group_points(guild_id, group_key)
    current_unix_timestamp = int(datetime.now(timezone.utc).timestamp())
    
    if guild_id not in LEADERBOARD_CACHE:
        LEADERBOARD_CACHE[guild_id] = {}
        
    if leader_data:
        sorted_users = sorted(leader_data.items(), key=lambda item: item[1], reverse=True)
        LEADERBOARD_CACHE[guild_id][group_key] = {
            'updated': current_unix_timestamp, 
            'top_users': sorted_users[:10]
        }
    else:
        LEADERBOARD_CACHE[guild_id][group_key] = {
            'updated': current_unix_timestamp, 
            'top_users': []
        }
        
    # 2. Update Permanent Message if it exists
    if group_key in PERMANENT_LEADERBOARDS:
        data = PERMANENT_LEADERBOARDS[group_key]
        try:
            channel = bot.get_channel(data['channel_id'])
            if channel and channel.guild:
                message = await channel.fetch_message(data['message_id'])
                new_embed = await _create_leaderboard_embed(channel.guild, group_key)
                await message.edit(embed=new_embed)
        except Exception as e:
            print(f"Error immediate update for {group_key}: {e}")

# --- Custom Check for Admins or Permitted Roles ---

def is_user_admin(member):
    """Checks if a member is an admin (Has Administrator permission OR is in ADMIN_ROLE_IDS)."""
    if member.guild_permissions.administrator:
        return True
    
    for role_id in ADMIN_ROLE_IDS:
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            return True
    return False

def check_admin_perms():
    def predicate(ctx):
        if is_user_admin(ctx.author):
            return True
        return False
    return commands.check(predicate)

# --- 7. EVENTS ---

@bot.event
async def on_ready():
    """Handles MongoDB connection and starts tasks."""
    global db
    
    try:
        print(f"Attempting to connect to MongoDB...")
        db = DatabaseHandler("", DB_NAME)
        print("Successfully connected to MongoDB!")

        await load_initial_config()

    except Exception as e:
        print(f"FATAL ERROR: Could not connect to MongoDB or load config. Bot will not function.")
        print(f"Connection Error: {e}")
        return

    print(f'Hello! I am logged in as {bot.user} with prefix "{PREFIX}"')
    voice_time_checker.start() 
    
    # Logic to align point_saver to clean 5-minute intervals
    now = datetime.now()
    current_total_seconds = now.minute * 60 + now.second
    seconds_past_last_5_min_mark = current_total_seconds % 300
    wait_time = 300 - seconds_past_last_5_min_mark
    
    if wait_time == 300:
        wait_time = 0

    if wait_time > 0:
        print(f"Waiting {wait_time} seconds to align point_saver to the next clean 5-minute mark...")
        await asyncio.sleep(wait_time)
    
    point_saver.change_interval(seconds=300) 
    point_saver.start() 
    print("Background tasks started.")

@bot.event
async def on_message(message):
    """Runs whenever a user sends a message or attachment."""
    if message.author.bot:
        return
        
    group_key = is_category_tracked(message.channel)
    if group_key:
        add_points_to_cache(message.author.id, message.guild.id, group_key, POINT_VALUES['message'])
        
        total_items = len(message.attachments) + len(message.embeds)
        if total_items > 0:
            points = total_items * POINT_VALUES['attachment']
            add_points_to_cache(message.author.id, message.guild.id, group_key, points)
            
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    """Runs when a message is deleted and logs it if a log channel is set."""
    if message.author.bot:
        return
        
    if LOG_CHANNEL_ID:
        deleter = None
        
        try:
            # Wait a brief moment for audit log to populate (it can be slow)
            await asyncio.sleep(0.5) 
            async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
                # Check if the audit log entry targets this message's author
                if entry.target.id == message.author.id:
                    # Verify it's recent (within 5 seconds)
                    time_diff = datetime.now(timezone.utc) - entry.created_at
                    if time_diff.total_seconds() < 5:
                        deleter = entry.user
                        break
        except Exception as e:
            print(f"Error checking audit logs: {e}")

        # If no audit log entry found, assume the author deleted it themselves
        if deleter is None:
            deleter = message.author

        # FINAL CHECK: If the person who deleted it is an Admin, DO NOT LOG.
        if is_user_admin(deleter):
            return 

        # --- LOGGING ---
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🗑️ Message Deleted",
                description=message.content if message.content else "*[No Text Content]*",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name=f"{message.author} (ID: {message.author.id})", icon_url=message.author.display_avatar.url)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            
            if message.attachments:
                att_list = "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
                embed.add_field(name="Attachments", value=att_list, inline=False)
                
            await log_channel.send(embed=embed)


@bot.event
async def on_reaction_add(reaction, user):
    """Runs whenever a user adds a reaction to a message."""
    if user.bot or not reaction.message.guild:
        return

    group_key = is_category_tracked(reaction.message.channel)
    if group_key:
        add_points_to_cache(user.id, reaction.message.guild.id, group_key, POINT_VALUES['reaction_add'])
        
        message_author = reaction.message.author
        if message_author.bot or user.id == message_author.id:
            return
            
        add_points_to_cache(message_author.id, reaction.message.guild.id, group_key, POINT_VALUES['reaction_receive'])

@bot.event
async def on_voice_state_update(member, before, after):
    """Runs whenever a user joins, leaves, or moves in a voice channel."""
    user_id = str(member.id)
    
    if member.bot:
        return
    
    group_key_after = is_category_tracked(after.channel) if after.channel else None

    if group_key_after and user_id not in VOICE_TRACKER:
        VOICE_TRACKER[user_id] = {'time': time.time(), 'group': group_key_after}
        
    elif user_id in VOICE_TRACKER and not group_key_after:
        del VOICE_TRACKER[user_id] 

# --- 8. TASKS (Background Jobs) ---

@tasks.loop(seconds=30.0) 
async def voice_time_checker():
    """Awards points for voice time and checks for VC notification."""
    current_time = time.time()
    
    # --- PART 1: POINT AWARDING ---
    for user_id_str, data in list(VOICE_TRACKER.items()): 
        join_time = data['time']
        group_key = data['group']
            
        time_diff = current_time - join_time 
        
        if time_diff >= 30.0:
            guild = bot.get_guild(data.get('guild_id'))
            member = guild.get_member(int(user_id_str)) if guild else None

            if member and member.voice and member.voice.channel:
                vc = member.voice.channel
                non_bot_users = sum(1 for m in vc.members if not m.bot)
                
                if non_bot_users >= 2:
                    points_earned = POINT_VALUES['voice_interval'] 
                    add_points_to_cache(int(user_id_str), guild.id, group_key, points_earned)
                
                VOICE_TRACKER[user_id_str]['time'] = current_time 
            
    # --- PART 2: VC NOTIFICATION LOGIC ---
    if VC_NOTIFY_ROLE_ID:
        for guild in bot.guilds:
            role = guild.get_role(VC_NOTIFY_ROLE_ID)
            if not role:
                continue

            for vc in guild.voice_channels:
                non_bot_members = [m for m in vc.members if not m.bot]
                
                if len(non_bot_members) >= 2:
                    if vc.id not in VC_ACTIVE_STATE:
                        VC_ACTIVE_STATE[vc.id] = {'start_time': current_time, 'pinged': False}
                    else:
                        data = VC_ACTIVE_STATE[vc.id]
                        elapsed = current_time - data['start_time']
                        
                        if elapsed >= 300 and not data['pinged']:
                            try:
                                await vc.send(role.mention)
                                data['pinged'] = True
                            except Exception as e:
                                print(f"Error pinging role in VC {vc.name}: {e}")
                else:
                    if vc.id in VC_ACTIVE_STATE:
                        del VC_ACTIVE_STATE[vc.id]


@tasks.loop(seconds=300.0) 
async def point_saver():
    """Merges in-memory points to MongoDB, saves, and updates permanent message."""
    global POINT_CACHE, LEADERBOARD_CACHE
    
    # 1. Merge cache to MongoDB
    if POINT_CACHE:
        for guild_id, groups in POINT_CACHE.items():
            for group_key, users in groups.items():
                for user_id, points in users.items():
                    try:
                        await db.update_user_points(guild_id, group_key, user_id, points)
                    except Exception as e:
                        print(f"ERROR saving points to DB for {user_id}: {e}")
        
        POINT_CACHE = {} 

    # 2. Pre-calculate and cache leaderboards
    new_leaderboard_cache = {}
    current_unix_timestamp = int(datetime.now(timezone.utc).timestamp())
    
    for guild in bot.guilds:
        guild_id = str(guild.id)
        new_leaderboard_cache[guild_id] = {}
        
        for group_key, group_data in LEADERBOARD_GROUPS.items():
            leader_data = await db.get_all_group_points(guild_id, group_key)
            
            if leader_data:
                sorted_users = sorted(leader_data.items(), key=lambda item: item[1], reverse=True)
                
                new_leaderboard_cache[guild_id][group_key] = {
                    'updated': current_unix_timestamp, 
                    'top_users': sorted_users[:10]
                }
            
    LEADERBOARD_CACHE = new_leaderboard_cache
    
    # 3. Update permanent leaderboard messages
    global PERMANENT_LEADERBOARDS
    for group_key, data in list(PERMANENT_LEADERBOARDS.items()): 
        try:
            channel = bot.get_channel(data['channel_id'])
            if channel and channel.guild:
                message = await channel.fetch_message(data['message_id'])
                new_embed = await _create_leaderboard_embed(channel.guild, group_key)
                await message.edit(embed=new_embed)
                print(f"Permanent Leaderboard for {group_key} updated in {channel.name}.")
            else:
                 print(f"Warning: Permanent Leaderboard Channel ID {data['channel_id']} not found or bot left guild.")

        except discord.NotFound:
            print(f"Warning: Permanent Leaderboard message or channel not found for {group_key}. Clearing setting.")
            del PERMANENT_LEADERBOARDS[group_key] 
        except Exception as e:
            print(f"Error updating permanent leaderboard for {group_key}: {e}")

    # 4. Save all configuration 
    await save_config_to_db() 
    print(f"Background save completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.")


# --- 9. COMMANDS ---

@bot.command(name='setlogchannel')
@commands.has_permissions(administrator=True)
async def set_log_channel(ctx, channel: discord.TextChannel):
    """^setlogchannel <#channel>: Sets the channel where deleted messages will be logged."""
    global LOG_CHANNEL_ID
    
    LOG_CHANNEL_ID = channel.id
    await save_config_to_db()
    
    await ctx.send(f"✅ Deleted messages will now be logged in {channel.mention}!")

@bot.command(name='setvcrole')
@commands.has_permissions(administrator=True)
async def set_vc_role(ctx, role: discord.Role):
    """^setvcrole <@Role>: Sets the role to ping when a VC has 2+ users for 5+ minutes."""
    global VC_NOTIFY_ROLE_ID
    
    VC_NOTIFY_ROLE_ID = role.id
    await save_config_to_db()
    
    await ctx.send(f"✅ VC Notification role set to **{role.name}**. I will ping them in the VC chat when 2+ people hang out for 5 minutes!")

@bot.command(name='setadmin')
@commands.has_permissions(administrator=True)
async def manage_admin_roles(ctx, action: str, role: discord.Role):
    """^setadmin <add/remove> <@Role>: Manages roles that can use point commands."""
    global ADMIN_ROLE_IDS
    
    action = action.lower()
    
    if action == 'add':
        if role.id not in ADMIN_ROLE_IDS:
            ADMIN_ROLE_IDS.append(role.id)
            await save_config_to_db()
            await ctx.send(f"✅ Role **{role.name}** added to Bot Admins.")
        else:
            await ctx.send(f"⚠️ Role **{role.name}** is already a Bot Admin.")
            
    elif action == 'remove':
        if role.id in ADMIN_ROLE_IDS:
            ADMIN_ROLE_IDS.remove(role.id)
            await save_config_to_db()
            await ctx.send(f"✅ Role **{role.name}** removed from Bot Admins.")
        else:
            await ctx.send(f"⚠️ Role **{role.name}** was not in the Bot Admin list.")
    else:
        await ctx.send(f"❌ Invalid action. Usage: `{PREFIX}setadmin add <@role>` or `{PREFIX}setadmin remove <@role>`.")

@bot.command(name='setleaderboard')
@commands.has_permissions(administrator=True) 
async def set_permanent_leaderboard(ctx, channel_id: int, message_id: int, group_key: str):
    """^setleaderboard <ChannelID> <MessageID> <GroupKey>: Sets a message to be permanently updated as a leaderboard."""
    global PERMANENT_LEADERBOARDS
    
    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{group_list}**.")
        return

    channel = bot.get_channel(channel_id)
    if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
        await ctx.send("❌ Channel ID is not a valid text channel.")
        return

    try:
        await channel.fetch_message(message_id)
    except discord.NotFound:
        await ctx.send("❌ Message ID not found in that channel.")
        return
    except Exception:
        await ctx.send("❌ Could not fetch message. Check permissions.")
        return


    PERMANENT_LEADERBOARDS[group_key] = {
        'channel_id': channel_id,
        'message_id': message_id,
        'group_key': group_key
    }
    await save_config_to_db()
    
    await ctx.send(f"✅ Permanent leaderboard message for **{LEADERBOARD_GROUPS[group_key]['name']}** set! It will update every 5 minutes.")

@bot.command(name='clearleaderboard')
@commands.has_permissions(administrator=True) 
async def clear_permanent_leaderboard(ctx, group_key: str = None):
    """^clearleaderboard [GroupKey]: Stops updating the permanent leaderboard message."""
    global PERMANENT_LEADERBOARDS
    
    if not group_key:
        group_list = ', '.join(PERMANENT_LEADERBOARDS.keys())
        if not group_list:
            await ctx.send("⚠️ No permanent leaderboard message is currently set.")
            return
        await ctx.send(f"❌ Please specify which group to clear. Options: **{group_list}**")
        return
        
    group_key = group_key.capitalize()
    
    if group_key not in PERMANENT_LEADERBOARDS:
        await ctx.send(f"⚠️ No permanent leaderboard message is set for group **{group_key}**.")
        return
        
    old_group_name = LEADERBOARD_GROUPS.get(group_key, {}).get('name', 'Unknown Group')
    
    del PERMANENT_LEADERBOARDS[group_key]
    await save_config_to_db()

    await ctx.send(f"🛑 Stopped updating the permanent leaderboard for **{old_group_name}**.")


@bot.command(name='clearpoints')
@commands.has_permissions(administrator=True) 
async def clear_group_points(ctx, group_key: str = None):
    """^clearpoints <GroupKey>: ADMIN command: Clears all points for a specified leaderboard group."""
    global LEADERBOARD_CACHE, POINT_CACHE
    
    if not group_key:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Please specify the group to clear. Available groups: **{group_list}**. Usage: `{PREFIX}clearpoints Group1`")
        return

    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found.")
        return

    group_name = LEADERBOARD_GROUPS[group_key]['name']
    guild_id = str(ctx.guild.id)
    
    # 1. Clear points from MongoDB
    deleted_count = await db.clear_points_by_group(guild_id, group_key)

    # 2. Clear points from in-memory caches
    if guild_id in LEADERBOARD_CACHE and group_key in LEADERBOARD_CACHE[guild_id]:
        del LEADERBOARD_CACHE[guild_id][group_key]
    if guild_id in POINT_CACHE and group_key in POINT_CACHE[guild_id]:
        del POINT_CACHE[guild_id][group_key]

    # 3. Update the permanent message immediately to show 0 points
    if not point_saver.is_running():
        await point_saver()

    await ctx.send(f"🗑️ Successfully cleared **{deleted_count}** user scores from the **{group_name}** leaderboard. The scores have been reset to 0!")


@bot.command(name='leaderboard')
async def show_leaderboard(ctx, group_key: str = None):
    """^leaderboard <GroupKey>: Displays the points leaderboard for the specified group from the cache."""
    if not group_key:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Please specify which leaderboard group you want to see. Available groups: **{group_list}**. Example: `{PREFIX}leaderboard Group1`")
        return

    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{group_list}**.")
        return
    
    embed = await _create_leaderboard_embed(ctx.guild, group_key)
    await ctx.send(embed=embed)


@bot.command(name='renamegroup')
@commands.has_permissions(administrator=True) 
async def rename_group(ctx, group_key: str = None, *, new_name: str = None):
    """^renamegroup <GroupKey> <New Name>: ADMIN command: Renames the display name of a leaderboard group."""
    global LEADERBOARD_GROUPS
    
    if not group_key or not new_name:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Missing arguments. Usage: `{PREFIX}renamegroup <GroupKey> <New Name>`\nAvailable group keys: **{group_list}**")
        return

    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group key **{group_key}** not found. Available keys: **{group_list}**.")
        return

    LEADERBOARD_GROUPS[group_key]['name'] = new_name
    await save_config_to_db()
    
    await ctx.send(f"✅ Group **{group_key}** has been successfully renamed to **{new_name}**!")

@bot.command(name='trackcategory')
@commands.has_permissions(administrator=True) 
async def track_category(ctx, group_key: str = None, category_id: int = None):
    """^trackcategory <GroupKey> <CategoryID>: ADMIN command: Adds a category ID to a specified group."""
    global LEADERBOARD_GROUPS
    
    if not group_key or category_id is None:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Missing arguments. Usage: `{PREFIX}trackcategory <GroupKey> <CategoryID>`\nAvailable groups: **{group_list}**")
        return

    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{group_list}**.")
        return

    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        await ctx.send("❌ That ID is not a valid Discord Category.")
        return

    is_tracked = is_category_tracked(category)
    if is_tracked:
        await ctx.send(f"⚠️ **{category.name}** is already being tracked by **{is_tracked}**. Remove it from that group first.")
        return

    LEADERBOARD_GROUPS[group_key]['categories'].append(category_id)
    await save_config_to_db() 
    await ctx.send(f"✅ Now tracking all channels in **{category.name}** for group **{LEADERBOARD_GROUPS[group_key]['name']}**!")

@bot.command(name='untrackcategory')
@commands.has_permissions(administrator=True) 
async def untrack_category(ctx, group_key: str = None, category_id: int = None):
    """^untrackcategory <GroupKey> <CategoryID>: ADMIN command: Removes a category ID from a specified group."""
    global LEADERBOARD_GROUPS
    
    if not group_key or category_id is None:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Missing arguments. Usage: `{PREFIX}untrackcategory <GroupKey> <CategoryID>`\nAvailable groups: **{group_list}**")
        return
        
    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{list}**.")
        return

    if category_id not in LEADERBOARD_GROUPS[group_key]['categories']:
        await ctx.send(f"⚠️ Category ID `{category_id}` was not found in group **{LEADERBOARD_GROUPS[group_key]['name']}**.")
        return

    LEADERBOARD_GROUPS[group_key]['categories'].remove(category_id)
    await save_config_to_db() 
    await ctx.send(f"🛑 Stopped tracking category ID `{category_id}` for group **{LEADERBOARD_GROUPS[group_key]['name']}**.")

@bot.command(name='award')
@check_admin_perms()
async def award_points(ctx, group_key: str, member: discord.Member, points: int):
    """^award <GroupKey> <@user> <points>: Awards points and updates leaderboard immediately."""
    
    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{group_list}**.")
        return

    if points <= 0:
        await ctx.send("❌ You must award a positive number of points.")
        return

    # 1. Update DB directly (Bypass Cache for immediate effect)
    await db.update_user_points(ctx.guild.id, group_key, member.id, points)
    
    # 2. Flush any pending cache for this user to DB (to avoid overwriting later)
    # Note: We don't strictly need to flush cache here if we just updated DB, 
    # but we should ensure the cache doesn't have stale 0 data that overwrites.
    # Simpler approach: Just refresh the leaderboard from DB now.
    
    # 3. Refresh Leaderboard & Permanent Message Immediately
    await refresh_group_leaderboard(ctx.guild, group_key)

    await ctx.send(f"✅ Awarded **{points}** points to **{member.display_name}** in **{LEADERBOARD_GROUPS[group_key]['name']}**.")
    
@bot.command(name='remove')
@check_admin_perms()
async def remove_points(ctx, group_key: str, member: discord.Member, points: int):
    """^remove <GroupKey> <@user> <points>: Removes points and updates leaderboard immediately."""
    
    group_key = group_key.capitalize()
    if group_key not in LEADERBOARD_GROUPS:
        group_list = ', '.join(LEADERBOARD_GROUPS.keys())
        await ctx.send(f"❌ Leaderboard group **{group_key}** not found. Available groups: **{group_list}**.")
        return

    if points <= 0:
        await ctx.send("❌ You must specify a positive number of points to remove.")
        return

    # 1. Update DB directly (negative points)
    await db.update_user_points(ctx.guild.id, group_key, member.id, -points)
    
    # 2. Refresh Leaderboard & Permanent Message Immediately
    await refresh_group_leaderboard(ctx.guild, group_key)

    await ctx.send(f"✅ Removed **{points}** points from **{member.display_name}** in **{LEADERBOARD_GROUPS[group_key]['name']}**.")

@bot.command(name='showpoints')
async def show_points(ctx):
    """^showpoints: Displays the current point values for all activities."""
    embed = discord.Embed(
        title="🌟 Current Point Values",
        description="These are the points earned for each activity.",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Messages", value=f"{POINT_VALUES.get('message', 0)} point(s)", inline=False)
    embed.add_field(name="Attachments", value=f"{POINT_VALUES.get('attachment', 0)} point(s)", inline=False)
    embed.add_field(name="Reactions Added (Reactor)", value=f"{POINT_VALUES.get('reaction_add', 0)} point(s)", inline=False)
    embed.add_field(name="Reactions Received (Author)", value=f"{POINT_VALUES.get('reaction_receive', 0)} point(s)", inline=False)
    
    points_per_minute = POINT_VALUES.get('voice_interval', 0) * 2
    embed.add_field(name="Voice Channel Time (per minute)", value=f"{points_per_minute} point(s)", inline=False)
    
    embed.set_footer(text=f"Change a value using {PREFIX}setpoints <activity> <value>")
    await ctx.send(embed=embed)

@bot.command(name='showsettings')
@commands.has_permissions(administrator=True)
async def show_settings_cmd(ctx):
    """^showsettings: Displays the current bot configuration."""
    embed = discord.Embed(title="⚙️ LeaderBug Settings", color=discord.Color.blue())
    
    # Groups
    groups_desc = ""
    for key, data in LEADERBOARD_GROUPS.items():
        cats = ", ".join([f"<#{c}>" for c in data['categories']]) if data['categories'] else "None"
        groups_desc += f"**{key}** ({data['name']}):\nCategories: {cats}\n\n"
    
    if not groups_desc: groups_desc = "No groups configured."
    embed.add_field(name="🏆 Leaderboard Groups", value=groups_desc, inline=False)
    
    # VC Role
    vc_role = f"<@&{VC_NOTIFY_ROLE_ID}>" if VC_NOTIFY_ROLE_ID else "None"
    embed.add_field(name="🔊 VC Notify Role", value=vc_role, inline=False)

    # Admin Roles
    if ADMIN_ROLE_IDS:
        admin_roles_str = ", ".join([f"<@&{rid}>" for rid in ADMIN_ROLE_IDS])
    else:
        admin_roles_str = "None"
    embed.add_field(name="🛡️ Bot Admin Roles", value=admin_roles_str, inline=False)

    # Log Channel
    log_channel = f"<#{LOG_CHANNEL_ID}>" if LOG_CHANNEL_ID else "None"
    embed.add_field(name="🗑️ Log Channel", value=log_channel, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='setpoints')
@commands.has_permissions(administrator=True) 
async def set_points(ctx, activity: str = None, value: int = None):
    """^setpoints <activity> <value>: ADMIN command: Sets the point value for an activity."""
    global POINT_VALUES
    
    activity_map = {
        'message': 'message', 'msg': 'message',
        'attachment': 'attachment', 'attachments': 'attachment',
        'react_add': 'reaction_add', 'reaction_add': 'reaction_add',
        'react_receive': 'reaction_receive', 'reaction_receive': 'reaction_receive',
        'voice': 'voice_interval', 'vc': 'voice_interval', 'time': 'voice_interval'
    }
    
    if not activity or value is None:
        await ctx.send(f"❌ Please provide an activity and a new value. Usage: `{PREFIX}setpoints <activity> <value>`\nAvailable activities: `message`, `attachment`, `react_add`, `react_receive`, `voice`.")
        return
    
    activity_key = activity_map.get(activity.lower())
    
    if not activity_key:
        await ctx.send(f"❌ Unknown activity: `{activity}`. Please use `message`, `attachment`, `react_add`, `react_receive`, or `voice`.")
        return

    if value < 0:
        await ctx.send("❌ Point values must be 0 or a positive number.")
        return

    # --- VOICE LOGIC for Points Per Minute (PPM) Input ---
    if activity_key == 'voice_interval':
        
        if value % 2 != 0:
            await ctx.send(f"⚠️ Warning: The points per minute must be an **even** number (e.g., 2, 4, 10) to be awarded fairly in the 30-second intervals. Your input ({value}) will be rounded down, and points will be lost.")
        
        value_to_store = value // 2
        
        if value_to_store == 0 and value > 0:
            await ctx.send(f"❌ The minimum effective setting is 2 points per minute (1 point per 30 seconds). Value must be 2 or greater.")
            return

        POINT_VALUES[activity_key] = value_to_store
        await save_config_to_db() 
        
        await ctx.send(f"✅ Points for **{activity}** updated to **{value}** points per minute (stored as **{value_to_store}** per 30 seconds).")
        return

    # --- NON-VOICE LOGIC ---
    POINT_VALUES[activity_key] = value
    await save_config_to_db() 

    await ctx.send(f"✅ Points for **{activity}** updated to **{value}** points.")

# --- 10. RUN THE BOT ---
if TOKEN:
    bot.run(TOKEN)
