import sys
sys.path.append('..')
from secret_bot import TOKEN as BOT_TOKEN
import discord
import random
import io
import asyncio
from datetime import datetime, timedelta
from discord.ext import commands
import json
import os

# --- CONFIGURATION ---
ADMIN_USER_ID = 1433003746719170560

# --- DATABASE SETUP ---
DB_FILE = "database.json"

class AsyncIterator:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        self.idx = 0
        return self
    async def __anext__(self):
        if self.idx >= len(self.items): raise StopAsyncIteration
        item = self.items[self.idx]
        self.idx += 1
        return item

class LocalCollection:
    def __init__(self, name):
        self.name = name

    def _load_all(self):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except: return {}

    def _save_all(self, data):
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4, default=str)

    async def find_one(self, query):
        all_data = self._load_all()
        collection = all_data.get(self.name, [])
        for doc in collection:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query={}):
        all_data = self._load_all()
        collection = all_data.get(self.name, [])
        results = [doc for doc in collection if all(doc.get(k) == v for k, v in query.items())]
        return AsyncIterator(results)

    async def insert_one(self, doc):
        all_data = self._load_all()
        if self.name not in all_data: all_data[self.name] = []
        all_data[self.name].append(doc)
        self._save_all(all_data)

    async def delete_one(self, query):
        all_data = self._load_all()
        collection = all_data.get(self.name, [])
        new_collection = [doc for doc in collection if not all(doc.get(k) == v for k, v in query.items())]
        all_data[self.name] = new_collection
        self._save_all(all_data)
        
    async def replace_one(self, query, doc, upsert=False):
        await self.delete_one(query)
        await self.insert_one(doc)

    # --- THE FIX IS HERE! ---
    async def update_one(self, query, update, upsert=False):
        all_data = self._load_all()
        if self.name not in all_data: all_data[self.name] = []
        
        collection = all_data[self.name]
        found = False
        
        for doc in collection:
            if all(doc.get(k) == v for k, v in query.items()):
                if "$set" in update:
                    doc.update(update["$set"])
                found = True
                break
        
        # If not found and upsert is True, create it!
        if not found and upsert:
            new_doc = query.copy()
            if "$set" in update:
                new_doc.update(update["$set"])
            collection.append(new_doc)
            found = True # We successfully "updated" by creating
        
        if found:
            self._save_all(all_data)
        return found

# --- COLLECTIONS ---
settings_col = LocalCollection("settings")
images_col = LocalCollection("images")

# --- MEMORY (CACHE) ---
settings_cache = {}
images_cache = {}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
intents.voice_states = True 

bot = commands.Bot(command_prefix="%", intents=intents, help_command=None)

# --- HELPER FUNCTIONS ---
def get_random_case(text):
    if not text:
        return "" 
    words = []
    for word in text.split():
        if word.startswith("http"):
            words.append(word)
        else:
            scrambled = "".join(random.choice([char.upper(), char.lower()]) for char in word)
            words.append(scrambled)
    return " ".join(words)

async def get_settings(guild_id):
    if guild_id in settings_cache:
        return settings_cache[guild_id]
    
    data = await settings_col.find_one({"_id": guild_id})
    if not data:
        result = {
            "image_target_id": None, 
            "react_target_id": None, 
            "reaction": None,
            "last_updated": None
        }
    else:
        result = {
            "image_target_id": data.get("image_target_id"),
            "react_target_id": data.get("react_target_id"),
            "reaction": data.get("reaction"),
            "last_updated": data.get("last_updated")
        }
    
    settings_cache[guild_id] = result
    return result

async def update_setting(guild_id, key, value):
    # This checks "upsert=True" which was crashing before!
    await settings_col.update_one({"_id": guild_id}, {"$set": {key: value}}, upsert=True)
    
    if guild_id not in settings_cache:
        settings_cache[guild_id] = {}
    settings_cache[guild_id][key] = value

async def get_guild_images(guild_id):
    if guild_id in images_cache:
        return images_cache[guild_id]

    cursor = images_col.find({"guild_id": guild_id})
    docs = await cursor.to_list(length=None)
    urls = [doc["url"] for doc in docs]
    
    images_cache[guild_id] = urls
    return urls

async def add_image_to_cache(guild_id, url):
    await images_col.insert_one({"guild_id": guild_id, "url": url})
    if guild_id in images_cache:
        images_cache[guild_id].append(url)
    else:
        images_cache[guild_id] = [url]

async def remove_image_from_cache(guild_id, url):
    result = await images_col.delete_one({"guild_id": guild_id, "url": url})
    if result.deleted_count > 0 and guild_id in images_cache:
        if url in images_cache[guild_id]:
            images_cache[guild_id].remove(url)
    return result.deleted_count > 0

async def check_cooldown(ctx):
    settings = await get_settings(ctx.guild.id)
    last_updated = settings.get("last_updated")
    
    if last_updated:
        # Handle string timestamps from JSON
        if isinstance(last_updated, str):
            try:
                last_updated = datetime.fromisoformat(last_updated)
            except:
                last_updated = None

        if last_updated:
            time_diff = datetime.utcnow() - last_updated
            if time_diff < timedelta(hours=2):
                hours_left = 2 - (time_diff.total_seconds() / 3600)
                await ctx.send(f"⏳ **Cooldown!** You must wait {hours_left:.1f} more hours before changing the target.")
                return False
    return True

# --- ADMIN CHECK ---
def is_bot_admin():
    async def predicate(ctx):
        if ctx.author.id == ADMIN_USER_ID:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)

# --- EVENTS ---

@bot.event
async def on_ready():
    print("--- BOTHERBUG IS READY ---")
    print(f"Logged in as {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if ctx.command and ctx.command.name == "add" and isinstance(error, commands.MissingRequiredArgument):
        return 

    if isinstance(error, (commands.MissingPermissions, commands.CheckFailure)):
        await ctx.send("🚫 You don't have permission to do that, buggy!")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❓ I couldn't find that member. Make sure to tag them!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("📝 You missed a required part of the command. Check %help!")
    else:
        if not isinstance(error, commands.CommandNotFound):
             print(f"Error: {error}")

@bot.event
async def on_member_update(before, after):
    """
    Watches for updates to members. 
    If the active troll target is muted or timed out, undo it immediately.
    """
    if after.bot: return

    settings = await get_settings(after.guild.id)
    target_id = settings.get("image_target_id")

    if target_id and after.id == target_id:
        
        # 1. Check for Timeout
        if after.timed_out_until:
            try:
                await after.timeout(None, reason="BotherBug Anti-Mute Protection")
                print(f"🛡️ Protected {after.display_name} from timeout.")
            except Exception as e:
                print(f"Failed to remove timeout from target: {e}")

        # 2. Check for Server Voice Mute
        if after.voice and after.voice.mute:
            try:
                await after.edit(mute=False, reason="BotherBug Anti-Mute Protection")
                print(f"🛡️ Protected {after.display_name} from voice mute.")
            except Exception as e:
                print(f"Failed to remove voice mute from target: {e}")

# --- COMMANDS ---

@bot.command(name="help")
@is_bot_admin()
async def custom_help(ctx):
    message = (
        "**BotherBug Commands (Admins Only):**\n"
        "`%start troll @user` - Steal a user's face and nickname (2hr Cooldown).\n"
        "`%stop troll` - Return to normal.\n"
        "`%start react @user` - Start reacting to a user's messages.\n"
        "`%stop react` - Stop reacting.\n"
        "`%select reaction [emoji]` - Set the emoji used for reacting.\n"
        "`%targets` - View the current troll and react targets.\n"
        "`%image list` - See all troll images.\n"
        "`%image add [url]` - Add a new image.\n"
        "`%image remove [url]` - Remove an image URL."
    )
    await ctx.send(message)

# --- START COMMANDS ---
@bot.group(name="start", invoke_without_command=True)
@is_bot_admin()
async def start(ctx):
    await ctx.send("❓ Start what? Try: `%start troll @user` or `%start react @user`")

@start.command(name="troll")
@is_bot_admin()
async def start_troll(ctx, member: discord.Member):
    if await check_cooldown(ctx):
        await update_setting(ctx.guild.id, "image_target_id", member.id)
        await update_setting(ctx.guild.id, "last_updated", datetime.utcnow())
        
        try:
            await ctx.guild.me.edit(nick=member.display_name)
            if member.avatar:
                avatar_bytes = await member.avatar.read()
                await bot.user.edit(avatar=avatar_bytes)
            await ctx.send(f"✅ **STARTED TROLLING!** I have stolen **{member.display_name}'s** face!")
        except discord.HTTPException as e:
            await ctx.send(f"⚠️ Discord blocked the face change (Rate Limit?): {e}")
        except Exception as e:
            await ctx.send(f"⚠️ Error changing identity: {e}")

@start.command(name="react")
@is_bot_admin()
async def start_react(ctx, member: discord.Member):
    if await check_cooldown(ctx):
        await update_setting(ctx.guild.id, "react_target_id", member.id)
        await update_setting(ctx.guild.id, "last_updated", datetime.utcnow())
        await ctx.send(f"✅ **STARTED REACTING!** I will react to **{member.display_name}**.")

# --- STOP COMMANDS ---
@bot.group(name="stop", invoke_without_command=True)
@is_bot_admin()
async def stop(ctx):
    await ctx.send("❓ Stop what? Try: `%stop troll` or `%stop react`")

@stop.command(name="troll")
@is_bot_admin()
async def stop_troll(ctx):
    await update_setting(ctx.guild.id, "image_target_id", None)
    
    try:
        await ctx.guild.me.edit(nick=None)
        await ctx.send("🛑 **STOPPED TROLLING!** I returned to my normal nickname.")
    except Exception as e:
        await ctx.send(f"🛑 Stopped trolling, but couldn't reset nickname: {e}")

@stop.command(name="react")
@is_bot_admin()
async def stop_react(ctx):
    await update_setting(ctx.guild.id, "react_target_id", None)
    await ctx.send("🛑 **STOPPED REACTING!**")

# --- OTHER COMMANDS ---
@bot.command(name="select")
@is_bot_admin()
async def select_shim(ctx, option: str = None, value: str = None):
    if option == "reaction" and value:
        await update_setting(ctx.guild.id, "reaction", value)
        await ctx.send(f"✅ Set reaction to: {value}")
    else:
        await ctx.send("ℹ️ Try using `%start troll` or `%start react` now!")

@bot.group(name="image", invoke_without_command=True)
@is_bot_admin()
async def image(ctx):
    await ctx.send("❓ Image what? Try: `list`, `add`, or `remove`.")

@image.command(name="list")
@is_bot_admin()
async def image_list(ctx):
    urls = await get_guild_images(ctx.guild.id)
    if not urls:
        await ctx.send("📂 The image list is empty.")
    else:
        msg = "**🖼️ Images:**\n"
        for url in urls:
            if len(msg) + len(url) > 1900:
                await ctx.send(msg)
                msg = ""
            msg += url + "\n"
        if msg:
            await ctx.send(msg)

@image.command(name="add")
@is_bot_admin()
async def image_add(ctx, url: str = None):
    if url is None:
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url
        else:
            await ctx.send("📝 Please provide a URL or attach an image!")
            return

    await add_image_to_cache(ctx.guild.id, url)
    await ctx.send(f"✅ Added image: {url}")

@image.command(name="remove")
@is_bot_admin()
async def image_remove(ctx, url: str):
    success = await remove_image_from_cache(ctx.guild.id, url)
    if success:
        await ctx.send("🗑️ Image removed.")
    else:
        await ctx.send("❓ I couldn't find that image.")

@bot.command(name="targets")
@is_bot_admin()
async def show_targets(ctx):
    settings = await get_settings(ctx.guild.id)
    
    img_target_id = settings.get("image_target_id")
    react_target_id = settings.get("react_target_id")
    reaction = settings.get("reaction") or "None"

    img_target_name = "None"
    if img_target_id:
        member = ctx.guild.get_member(img_target_id)
        img_target_name = member.display_name if member else "Unknown"

    react_target_name = "None"
    if react_target_id:
        member = ctx.guild.get_member(react_target_id)
        react_target_name = member.display_name if member else "Unknown"

    msg = (
        "**🎯 Current Troll Targets:**\n"
        f"😈 **Image Swap Target:** {img_target_name}\n"
        f"😂 **React Target:** {react_target_name}\n"
        f"🎭 **Reaction:** {reaction}"
    )
    await ctx.send(msg)

# --- MESSAGE LISTENER ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    settings = await get_settings(message.guild.id)

    # 0. Handle Ping Forwarding
    if bot.user in message.mentions:
        target_id = settings.get("image_target_id")
        if target_id:
            try:
                await message.channel.send(f"<@{target_id}>")
            except:
                pass

    await bot.process_commands(message)

    # 1. Handle Reactions
    if settings.get("react_target_id") == message.author.id:
        if settings.get("reaction"):
            try:
                await message.add_reaction(settings["reaction"])
            except:
                pass 

    # 2. Handle Image/Message Swap
    if settings.get("image_target_id") == message.author.id:
        
        new_text = get_random_case(message.content)
        
        files_to_send = []
        if message.attachments:
            for attachment in message.attachments:
                try:
                    data = await attachment.read()
                    f = discord.File(io.BytesIO(data), filename=attachment.filename)
                    files_to_send.append(f)
                except Exception as e:
                    print(f"Failed to process image: {e}")
        
        if not files_to_send and "http" not in new_text:
            docs = await get_guild_images(message.guild.id)
            if docs:
                if random.random() < 0.3:
                    random_url = random.choice(docs)
                    new_text += f"\n{random_url}"

        if not new_text and not files_to_send:
            return

        ref = None
        should_mention_author = True 

        if message.reference:
            ref = message.reference
            if ref.cached_message:
                if ref.cached_message.author not in message.mentions:
                    should_mention_author = False
            elif not message.mentions:
                should_mention_author = False

        try:
            await message.delete()
            await message.channel.send(
                content=new_text,
                files=files_to_send,
                reference=ref,
                mention_author=should_mention_author 
            )
        except Exception as e:
            print(f"Failed to send swap: {e}")

# --- RUN ---
bot.run(BOT_TOKEN)
