import sys
sys.path.append('..')
from secret_bot import TOKEN
import discord
from discord.ext import commands
# import motor.motor_asyncio

# --- CONFIGURATION ---

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="$", intents=intents)

# --- DATABASE CONNECTION ---
# --- DATABASE CONNECTION (LOCAL FILE VERSION) ---
import json
import os

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

    async def update_one(self, query, update):
        all_data = self._load_all()
        collection = all_data.get(self.name, [])
        found = False
        for doc in collection:
            # Check if this doc matches the query
            if all(doc.get(k) == v for k, v in query.items()):
                # Handle $set update
                if "$set" in update:
                    doc.update(update["$set"])
                found = True
                break
        
        if found:
            self._save_all(all_data)
        return found


# --- REPLACED CONNECTION ---
# cluster = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
# db = cluster["puppypet_db"]
settings_col = LocalCollection("settings")

# --- DEFAULT SETTINGS ---
config = {
    "source_category_ids": [
        1434627845392695429,
        1441588870297813133,
        1441603802905055242,
        1441602427265613988,
        1441603192734482504,
        1441624360271220886,
        1441604257328529558
    ],
    "copy_channel_id": 1441945844340359348,
    "blocked_channel_ids": [
        1441945844340359348,
        1435033436107706409,
        1433930334730326137,
        1441608109893091422,
        1438210264511283261
    ]
}

@bot.event
async def on_ready():
    global config
    print(f'Bot is ready! Logged in as {bot.user}')
    
    # Load settings from Database
    data = await settings_col.find_one({"_id": "config"})
    if not data:
        await settings_col.insert_one({"_id": "config", **config})
        print("Initialized database with default settings.")
    else:
        config["source_category_ids"] = data.get("source_category_ids", config["source_category_ids"])
        config["copy_channel_id"] = data.get("copy_channel_id", config["copy_channel_id"])
        config["blocked_channel_ids"] = data.get("blocked_channel_ids", config["blocked_channel_ids"])
        print("Loaded settings from database.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Check if channel is IGNORED
    if message.channel.id in config['blocked_channel_ids']:
        await bot.process_commands(message)
        return

    # 2. Check if channel is in a CATEGORY TO COPY
    if message.channel.category and message.channel.category.id in config['source_category_ids']:
        
        # 3. Check for Attachments OR Embeds (Filter out plain text)
        if message.attachments or message.embeds:
            target_id = config['copy_channel_id']
            target_channel = bot.get_channel(target_id)

            if target_channel:
                # 4. Webhook Impersonation
                webhooks = await target_channel.webhooks()
                webhook = discord.utils.get(webhooks, name="PuppyPetHook")
                
                if not webhook:
                    webhook = await target_channel.create_webhook(name="PuppyPetHook")

                # Prepare content: Original text + Attachment Links
                content_to_send = message.content
                
                if message.attachments:
                    # Add a new line if there is already text
                    if content_to_send:
                        content_to_send += "\n"
                    # Add all the file links
                    content_to_send += "\n".join([att.url for att in message.attachments])

                try:
                    await webhook.send(
                        content=content_to_send,
                        username=message.author.display_name,
                        avatar_url=message.author.display_avatar.url,
                        embeds=message.embeds, # This copies embeds too!
                        wait=True
                    )
                except Exception as e:
                    print(f"Error sending webhook: {e}")

    await bot.process_commands(message)

# --- MANAGEMENT COMMANDS ---

@bot.command()
@commands.has_permissions(administrator=True)
async def listsettings(ctx):
    """Lists the Categories to Copy and Channels to Ignore."""
    text = "__**PuppyPet Settings**__\n"
    
    text += "\n**📂 Categories to Copy:**\n"
    cats = config['source_category_ids']
    if cats:
        text += "\n".join([f"• <#{c}> (`{c}`)" for c in cats])
    else:
        text += "(None)"

    text += "\n\n**🚫 Channels to Ignore:**\n"
    blocked = config['blocked_channel_ids']
    if blocked:
        text += "\n".join([f"• <#{c}> (`{c}`)" for c in blocked])
    else:
        text += "(None)"

    text += f"\n\n**🎯 Target Channel:** <#{config['copy_channel_id']}>"
    
    await ctx.send(text)

@bot.command()
@commands.has_permissions(administrator=True)
async def category(ctx, action: str, category_id: int):
    """Usage: $category <add|remove> <ID>"""
    action = action.lower()
    
    if action == 'add':
        if category_id not in config['source_category_ids']:
            config['source_category_ids'].append(category_id)
            await settings_col.update_one({"_id": "config"}, {"$set": {"source_category_ids": config['source_category_ids']}})
            await ctx.send(f"✅ Added category <#{category_id}> to the **Copy List**, buggy!")
        else:
            await ctx.send("That category is already on the list, buggy.")
            
    elif action == 'remove':
        if category_id in config['source_category_ids']:
            config['source_category_ids'].remove(category_id)
            await settings_col.update_one({"_id": "config"}, {"$set": {"source_category_ids": config['source_category_ids']}})
            await ctx.send(f"🗑️ Removed category <#{category_id}> from the **Copy List**, buggy!")
        else:
            await ctx.send("That category isn't on the list, buggy.")
    else:
        await ctx.send("Please use `add` or `remove`, buggy! Example: `$category add 123456789`")

@bot.command()
@commands.has_permissions(administrator=True)
async def ignore(ctx, action: str, channel_id: int):
    """Usage: $ignore <add|remove> <ID>"""
    action = action.lower()
    
    if action == 'add':
        if channel_id not in config['blocked_channel_ids']:
            config['blocked_channel_ids'].append(channel_id)
            await settings_col.update_one({"_id": "config"}, {"$set": {"blocked_channel_ids": config['blocked_channel_ids']}})
            await ctx.send(f"✅ Added channel <#{channel_id}> to the **Ignore List**, buggy!")
        else:
            await ctx.send("That channel is already ignored, buggy.")
            
    elif action == 'remove':
        if channel_id in config['blocked_channel_ids']:
            config['blocked_channel_ids'].remove(channel_id)
            await settings_col.update_one({"_id": "config"}, {"$set": {"blocked_channel_ids": config['blocked_channel_ids']}})
            await ctx.send(f"🗑️ Removed channel <#{channel_id}> from the **Ignore List**, buggy!")
        else:
            await ctx.send("That channel isn't ignored, buggy.")
    else:
        await ctx.send("Please use `add` or `remove`, buggy! Example: `$ignore add 123456789`")

@bot.command()
@commands.has_permissions(administrator=True)
async def settarget(ctx, channel_id: int):
    """Sets the channel where messages are copied to."""
    config['copy_channel_id'] = channel_id
    await settings_col.update_one({"_id": "config"}, {"$set": {"copy_channel_id": channel_id}})
    await ctx.send(f"🎯 Set the **Target Channel** to <#{channel_id}>, buggy!")

bot.run(TOKEN)
