import discord
from discord.ext import commands
import json
import os
from secret_bot import TOKEN

# --- 1. DATABASE HANDLER (Local System) ---
DB_FILE = "database.json"

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

    async def update_one(self, query, update, upsert=False):
        all_data = self._load_all()
        if self.name not in all_data: all_data[self.name] = []
        
        found = False
        for doc in all_data[self.name]:
            if all(doc.get(k) == v for k, v in query.items()):
                if "$set" in update:
                    doc.update(update["$set"])
                found = True
                break
        
        if not found and upsert:
            new_doc = query.copy()
            if "$set" in update:
                new_doc.update(update["$set"])
            all_data[self.name].append(new_doc)

        self._save_all(all_data)

# Connect to a unique collection for BadBug
config_col = LocalCollection("badbug_config")

# --- 2. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cache for speed
config_cache = {
    "log_channel": None, 
    "access_msg_id": None, 
    "ticket_channels": []
}

async def load_config():
    data = await config_col.find_one({"_id": "settings"})
    if data:
        config_cache["log_channel"] = data.get("log_channel")
        config_cache["access_msg_id"] = data.get("access_msg_id")
        config_cache["ticket_channels"] = data.get("ticket_channels", [])
    else:
        await config_col.update_one(
            {"_id": "settings"}, 
            {"$set": config_cache}, 
            upsert=True
        )

@bot.event
async def on_ready():
    await load_config()
    print(f'BadBug is ready! Logged in as {bot.user}')

# --- 3. COMMANDS (ADMIN ONLY) ---

@bot.command()
@commands.has_permissions(administrator=True) # <--- This protects the command!
async def showsettings(ctx):
    """Shows the current configuration."""
    log_ch = f"<#{config_cache['log_channel']}>" if config_cache['log_channel'] else "None"
    msg_id = config_cache['access_msg_id'] if config_cache['access_msg_id'] else "None"
    
    await ctx.send(
        f"**⚙️ BadBug Settings**\n"
        f"📝 **Log Channel:** {log_ch}\n"
        f"🔘 **Ticket Button Message ID:** `{msg_id}`\n"
        f"📂 **Active Ticket Channels:** {len(config_cache['ticket_channels'])}"
    )

@bot.command()
@commands.has_permissions(administrator=True) # <--- This protects the command!
async def setlog(ctx):
    """Sets the current channel as the join/leave log channel."""
    config_cache['log_channel'] = ctx.channel.id
    await config_col.update_one({"_id": "settings"}, {"$set": {"log_channel": ctx.channel.id}})
    await ctx.send(f"✅ **Log Channel** set to {ctx.channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True) # <--- This protects the command!
async def setaccess(ctx, msg_id: int):
    """Sets the message that users react to for a ticket."""
    config_cache['access_msg_id'] = msg_id
    await config_col.update_one({"_id": "settings"}, {"$set": {"access_msg_id": msg_id}})
    await ctx.send(f"✅ **Ticket Button** set to message ID: `{msg_id}`")

@bot.command()
@commands.has_permissions(administrator=True) # <--- This protects the command!
async def add(ctx, member: discord.Member, channel: discord.TextChannel = None):
    """Allows a user to view a private channel."""
    target_channel = channel or ctx.channel
    await target_channel.set_permissions(member, view_channel=True, send_messages=True)
    await ctx.send(f"✅ Added {member.mention} to {target_channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True) # <--- This protects the command!
async def remove(ctx, member: discord.Member, channel: discord.TextChannel = None):
    """Removes a user's view privileges from a channel."""
    target_channel = channel or ctx.channel
    await target_channel.set_permissions(member, overwrite=None)
    await ctx.send(f"❌ Removed {member.mention} from {target_channel.mention}")

# --- 4. EVENTS ---

@bot.event
async def on_member_join(member):
    if config_cache['log_channel']:
        channel = bot.get_channel(config_cache['log_channel'])
        if channel:
            await channel.send(f"**Joined** 🟢\n{member.mention}\nID: `{member.id}`")

@bot.event
async def on_member_remove(member):
    if config_cache['log_channel']:
        channel = bot.get_channel(config_cache['log_channel'])
        if channel:
            await channel.send(f"**Left** 🔴\n{member.mention}\nID: `{member.id}`")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: return
    
    if payload.message_id == config_cache['access_msg_id']:
        guild = bot.get_guild(payload.guild_id)
        channel = bot.get_channel(payload.channel_id)
        try:
            msg = await channel.fetch_message(payload.message_id)
            await msg.remove_reaction(payload.emoji, payload.member)
        except: pass

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            payload.member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        
        ticket_name = f"ticket-{payload.member.name}"
        ticket_channel = await guild.create_text_channel(ticket_name, overwrites=overwrites)
        
        config_cache['ticket_channels'].append(ticket_channel.id)
        await config_col.update_one(
            {"_id": "settings"}, 
            {"$set": {"ticket_channels": config_cache['ticket_channels']}}
        )
        
        await ticket_channel.send(
            f"{payload.member.mention} **Welcome!**\n"
            "📝 Please request your access here.\n"
            "⚠️ **Rule:** You can ONLY send messages with **Images, Videos, or Links**.\n"
            "Plain text messages will be deleted!"
        )

@bot.event
async def on_message(message):
    if message.author.bot: return
    
    if message.channel.id in config_cache['ticket_channels']:
        has_attachment = bool(message.attachments)
        has_embed = bool(message.embeds)
        has_link = "http" in message.content
        
        if not (has_attachment or has_embed or has_link):
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} ❌ **Media/Links Only!** Plain text is not allowed here.", 
                    delete_after=5
                )
            except: pass
            return

    await bot.process_commands(message)

# This handles the error if a non-admin tries to use a command
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 **Access Denied:** You need to be an Admin to use this command!")

if TOKEN:
    bot.run(TOKEN)
