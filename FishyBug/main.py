import sys
sys.path.append('..')
try:
    from secret_bot import TOKEN
except ImportError:
    print("Error: secret_bot.py not found. Please create it with TOKEN = '...'")
    sys.exit()

import discord
from discord.ext import commands
import json
import os
import asyncio

# --- FUNCTION LIST ---
# 1. LocalCollection Class: Handles database.json interactions.
# 2. load_config(): Loads the bot settings from the database.
# 3. save_config_cache(): Updates the database with the current memory cache.
# 4. Command: settings(): Shows configurations.
# 5. Command: setmessage(message_id): Sets the ID to react to.
# 6. Command: setreaction(emoji): Sets the emoji to react with.
# 7. Command: nameticket(name): Sets ticket channel name format.
# 8. Command: ticketquestion(question): Sets the opening prompt.
# 9. Command: setcategory(category_id): Sets ticket category.
# 10. Command: setrole(role): Sets the role to GIVE.
# 11. Command: setderole(role): Sets the role to REMOVE (New!).
# 12. Event: on_ready(): Startup sequence.
# 13. Event: on_raw_reaction_add(payload): Handles ticket creation.
# 14. Event: on_message(message): Handles age verification logic.

# --- 1. DATABASE HANDLER ---
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

config_col = LocalCollection("nsfw_ticket_config")

# --- 2. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="$", intents=intents)

# Default Config
config_cache = {
    "reaction_message_id": None,
    "reaction_emoji": "🔞",
    "ticket_name_format": "verify-{user}",
    "ticket_question": "{user}, please enter your age to verify access.",
    "ticket_category_id": None,
    "verified_role_id": None,
    "derole_id": None, # <--- NEW FIELD
    "active_tickets": [] 
}

async def load_config():
    data = await config_col.find_one({"_id": "settings"})
    if data:
        config_cache["reaction_message_id"] = data.get("reaction_message_id")
        config_cache["reaction_emoji"] = data.get("reaction_emoji", "🔞")
        config_cache["ticket_name_format"] = data.get("ticket_name_format", "verify-{user}")
        config_cache["ticket_question"] = data.get("ticket_question", "{user}, please enter your age to verify access.")
        config_cache["ticket_category_id"] = data.get("ticket_category_id")
        config_cache["verified_role_id"] = data.get("verified_role_id")
        config_cache["derole_id"] = data.get("derole_id") # <--- Load New Field
        config_cache["active_tickets"] = data.get("active_tickets", [])
    else:
        await save_config_cache()

async def save_config_cache():
    await config_col.update_one(
        {"_id": "settings"}, 
        {"$set": config_cache}, 
        upsert=True
    )

# --- 3. COMMANDS ---

@bot.command()
@commands.has_permissions(administrator=True)
async def settings(ctx):
    msg = "**🔧 NSFW Ticket Settings**\n"
    msg += f"**Message ID:** `{config_cache['reaction_message_id']}`\n"
    msg += f"**Reaction:** {config_cache['reaction_emoji']}\n"
    msg += f"**Ticket Name:** `{config_cache['ticket_name_format']}`\n"
    msg += f"**Question:** `{config_cache['ticket_question']}`\n"
    msg += f"**Category ID:** `{config_cache['ticket_category_id']}`\n"
    msg += f"**Give Role ID:** `{config_cache['verified_role_id']}`\n"
    msg += f"**Remove Role ID:** `{config_cache['derole_id']}`"
    await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def setmessage(ctx, message_id: str):
    try:
        config_cache['reaction_message_id'] = int(message_id)
        await save_config_cache()
        await ctx.send(f"✅ Set reaction message ID to `{message_id}`.")
    except ValueError:
        await ctx.send("❌ Please provide a valid number for the message ID.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setreaction(ctx, emoji: str):
    config_cache['reaction_emoji'] = emoji
    await save_config_cache()
    await ctx.send(f"✅ Set reaction emoji to {emoji}.")

@bot.command()
@commands.has_permissions(administrator=True)
async def nameticket(ctx, name: str):
    config_cache['ticket_name_format'] = name
    await save_config_cache()
    await ctx.send(f"✅ Ticket names will now look like: `{name}` (Use `{{user}}` for username).")

@bot.command()
@commands.has_permissions(administrator=True)
async def ticketquestion(ctx, *, question: str):
    config_cache['ticket_question'] = question
    await save_config_cache()
    await ctx.send(f"✅ Ticket opening message set.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setcategory(ctx, category_id: str):
    try:
        config_cache['ticket_category_id'] = int(category_id)
        await save_config_cache()
        await ctx.send(f"✅ Tickets will be created in Category ID `{category_id}`.")
    except ValueError:
        await ctx.send("❌ Please provide a valid number for the Category ID.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setrole(ctx, role: discord.Role):
    config_cache['verified_role_id'] = role.id
    await save_config_cache()
    await ctx.send(f"✅ Verified users will RECEIVE the **{role.name}** role.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setderole(ctx, role: discord.Role):
    config_cache['derole_id'] = role.id
    await save_config_cache()
    await ctx.send(f"✅ Verified users will LOSE the **{role.name}** role.")

# --- 4. EVENTS ---

@bot.event
async def on_ready():
    await load_config()
    print(f'NSFW Ticket Bot is ready! Logged in as {bot.user}')

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: return

    # Check if it matches our set message and emoji
    if (payload.message_id == config_cache['reaction_message_id'] and 
        str(payload.emoji) == config_cache['reaction_emoji']):
        
        guild = bot.get_guild(payload.guild_id)
        if not guild: return
        
        # 1. Remove the reaction immediately
        channel = bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, payload.member)
        except: pass

        # 2. Check Permissions / Roles
        if config_cache['verified_role_id']:
            role = guild.get_role(config_cache['verified_role_id'])
            if role in payload.member.roles:
                return # They are already verified

        # 3. Create Ticket
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            payload.member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        
        category = None
        if config_cache['ticket_category_id']:
            category = guild.get_channel(config_cache['ticket_category_id'])

        ticket_name = config_cache['ticket_name_format'].replace("{user}", payload.member.name.lower())
        
        try:
            ticket_channel = await guild.create_text_channel(ticket_name, overwrites=overwrites, category=category)
            
            # Save to active tickets list
            config_cache['active_tickets'].append(ticket_channel.id)
            await save_config_cache()

            # Send opening question
            question = config_cache['ticket_question'].replace("{user}", payload.member.mention)
            await ticket_channel.send(question)
        
        except Exception as e:
            print(f"Failed to create ticket: {e}")

@bot.event
async def on_message(message):
    if message.author.bot: return

    # Check if message is in an active ticket channel
    if message.channel.id in config_cache['active_tickets']:
        
        # Ignore Admins (so you can moderate)
        if message.author.guild_permissions.administrator:
            await bot.process_commands(message)
            return

        # AGE VERIFICATION LOGIC
        content = message.content.strip()

        # 1. Check if it is a number
        if not content.isdigit():
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention} ⚠️ Please enter **only** a number (your age).", delete_after=5)
            except: pass
            return

        age = int(content)

        # 2. Check Age
        if age < 18:
            # BAN
            try:
                await message.channel.send("🚫 **Access Denied.** You are under 18.")
                await message.author.ban(reason=f"Age verification failed: User stated they are {age}.")
                # Close Ticket
                await asyncio.sleep(2)
                await message.channel.delete()
                
                if message.channel.id in config_cache['active_tickets']:
                    config_cache['active_tickets'].remove(message.channel.id)
                    await save_config_cache()
            except Exception as e:
                await message.channel.send(f"❌ Failed to ban user: {e}")

        else:
            # GIVE ROLE & REMOVE ROLE
            role_id = config_cache['verified_role_id']
            derole_id = config_cache['derole_id']
            
            role_given = False
            role_removed = False
            
            if role_id:
                role = message.guild.get_role(role_id)
                if role:
                    try:
                        await message.author.add_roles(role)
                        role_given = True
                    except: pass
            
            if derole_id:
                derole = message.guild.get_role(derole_id)
                if derole:
                    try:
                        await message.author.remove_roles(derole)
                        role_removed = True
                    except: pass
            
            if role_given:
                success_msg = f"✅ **Verified!** You have been given the {role.name} role."
                if role_removed:
                    success_msg += f" (Removed {derole.name})"
                
                await message.channel.send(success_msg)
                
                # Close Ticket
                await asyncio.sleep(5)
                await message.channel.delete()

                if message.channel.id in config_cache['active_tickets']:
                    config_cache['active_tickets'].remove(message.channel.id)
                    await save_config_cache()
            else:
                 await message.channel.send("❌ Error: No Verified Role configured. Contact Admin.")

    await bot.process_commands(message)

if TOKEN:
    bot.run(TOKEN)
