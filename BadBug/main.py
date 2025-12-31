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

config_col = LocalCollection("badbug_config")

# --- 2. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cache
config_cache = {
    "log_channel": None, 
    "access_msg_id": None, 
    "access_channel_id": None, # Stored to make the link work!
    "ticket_category": None, 
    "ticket_channels": []
}

async def load_config():
    data = await config_col.find_one({"_id": "settings"})
    if data:
        config_cache["log_channel"] = data.get("log_channel")
        config_cache["access_msg_id"] = data.get("access_msg_id")
        config_cache["access_channel_id"] = data.get("access_channel_id")
        config_cache["ticket_category"] = data.get("ticket_category")
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
@commands.has_permissions(administrator=True)
async def settings(ctx):
    # Construct "link to access" (The Jump URL)
    access_link = "None"
    if config_cache['access_msg_id'] and config_cache['access_channel_id']:
        # Format: https://discord.com/channels/GUILD_ID/CHANNEL_ID/MSG_ID
        access_link = f"https://discord.com/channels/{ctx.guild.id}/{config_cache['access_channel_id']}/{config_cache['access_msg_id']}"
    elif config_cache['access_msg_id']:
        access_link = f"ID: {config_cache['access_msg_id']} (Channel unknown)"

    # Category link (Mention)
    cat_link = f"<#{config_cache['ticket_category']}>" if config_cache['ticket_category'] else "None"
    
    # Log link
    log_link = f"<#{config_cache['log_channel']}>" if config_cache['log_channel'] else "None"

    # Tickets count
    ticket_count = len(config_cache['ticket_channels'])
    
    msg = (
        f"log: {log_link}\n"
        f"access: {access_link}\n"
        f"category: {cat_link}\n"
        f"tickets: {ticket_count}"
    )
    await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def log(ctx):
    """Sets the current channel as the log channel."""
    config_cache['log_channel'] = ctx.channel.id
    await config_col.update_one({"_id": "settings"}, {"$set": {"log_channel": ctx.channel.id}})
    await ctx.send(f"✅ **Log Channel** set to {ctx.channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def category(ctx, cat: discord.CategoryChannel):
    """Sets the category for new tickets (Usage: !category ID_OR_NAME)."""
    config_cache['ticket_category'] = cat.id
    await config_col.update_one({"_id": "settings"}, {"$set": {"ticket_category": cat.id}})
    await ctx.send(f"✅ **Ticket Category** set to {cat.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def access(ctx, message: discord.Message):
    """Sets the access button. (Usage: !access <Message_Link_or_ID>)."""
    config_cache['access_msg_id'] = message.id
    config_cache['access_channel_id'] = message.channel.id
    
    await config_col.update_one(
        {"_id": "settings"}, 
        {"$set": {
            "access_msg_id": message.id,
            "access_channel_id": message.channel.id
        }}
    )
    await ctx.send(f"✅ **Access Button** linked to [Message]({message.jump_url})")

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, member: discord.Member, channel: discord.TextChannel = None):
    target_channel = channel or ctx.channel
    await target_channel.set_permissions(member, view_channel=True, send_messages=True)
    await ctx.send(f"✅ Added {member.mention} to {target_channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, member: discord.Member, channel: discord.TextChannel = None):
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
        
        # Cleanup reaction
        channel = bot.get_channel(payload.channel_id)
        try:
            msg = await channel.fetch_message(payload.message_id)
            await msg.remove_reaction(payload.emoji, payload.member)
        except: pass

        # Overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            payload.member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        
        # Get Category
        cat = None
        if config_cache['ticket_category']:
            cat = guild.get_channel(config_cache['ticket_category'])

        ticket_name = f"ticket-{payload.member.name}"
        # Create with category
        ticket_channel = await guild.create_text_channel(ticket_name, overwrites=overwrites, category=cat)
        
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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 **Access Denied:** You need to be an Admin to use this command!")
    elif isinstance(error, commands.BadArgument):
         await ctx.send("⚠️ **Error:** I couldn't find that! \nFor `!access` or `!category`, make sure you are pasting a valid ID or Link.")
    else:
        print(f"Error: {error}")

if TOKEN:
    bot.run(TOKEN)
