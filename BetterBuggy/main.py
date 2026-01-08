import discord
from discord.ext import commands
import json
import os
import re
import asyncio
import sys

# Try to import the token from secret_bot.py in the same folder
try:
    from secret_bot import TOKEN
except ImportError:
    print("Error: secret_bot.py not found. Please make sure it is in the same folder as main.py and contains TOKEN = '...'")
    sys.exit()

# --- FUNCTION LIST ---
# 1. LocalCollection Class: Handles database.json interactions.
# 2. Config & DB Setup: Loads settings and active tasks.
# 3. TaskView Class: The UI for the progress bar (Buttons & Logic).
# 4. Helper: get_emoji_bar(state): Creates the 30x2 grid using consistent square emojis.
# 5. Helper: get_celebratory_message(percent): Picks the right message.
# 6. Event: on_ready(): Startup sequence & View persistence.
# 7. Event: on_message(message): Handles Sleep commands & Task creation.
# 8. Command: setsleepvc(channel_id): Configures the Sleep VC.
# 9. Command: setmessage(level, text): Configures celebration messages.
# 10. Command: settings(): Shows current config.

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

    async def find_all(self):
        all_data = self._load_all()
        return all_data.get(self.name, [])

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

# Collections
config_col = LocalCollection("betterbuggy_config")
tasks_col = LocalCollection("betterbuggy_tasks")

# --- 2. CONFIG & SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cache
config_cache = {
    "sleep_vc_id": None,
    "celebratory_messages": {
        "1": "Good start! Keep it up!",           # 0-24
        "2": "You're making progress!",           # 25-49
        "3": "Almost there, doing great!",        # 50-74
        "4": "AMAZING! You finished the list!"    # 75-100
    }
}

async def load_config():
    data = await config_col.find_one({"_id": "settings"})
    if data:
        config_cache["sleep_vc_id"] = data.get("sleep_vc_id")
        saved_msgs = data.get("celebratory_messages", {})
        config_cache["celebratory_messages"].update(saved_msgs)
    else:
        await config_col.update_one({"_id": "settings"}, {"$set": config_cache}, upsert=True)

# --- 3. TASK VIEW CLASS ---
# State Codes: 0 = White (Todo), 1 = Green (Done), 2 = Blue (Skipped)

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
        
        # Grid Size: 16 Columns x 2 Rows = 32 Squares total
        cols = 16
        rows = 2
        total_visual_blocks = cols * rows
        
        # We need to map 'self.total' tasks onto '32' visual squares.
        # We will create an expanded list representing the visual state.
        
        visual_state = []
        
        # Create a visual representation by repeating task states proportionally
        current_visual_count = 0
        for i in range(self.total):
            # Calculate how many visual blocks this task should take up
            # We use cumulative calculation to avoid rounding errors accumulating
            target_visual_count = int((i + 1) * total_visual_blocks / self.total)
            blocks_for_this_task = target_visual_count - current_visual_count
            
            visual_state.extend([self.state[i]] * blocks_for_this_task)
            current_visual_count += blocks_for_this_task
            
        # Safety check to ensure exactly 32 blocks
        if len(visual_state) < total_visual_blocks:
            visual_state.extend([0] * (total_visual_blocks - len(visual_state)))
        elif len(visual_state) > total_visual_blocks:
            visual_state = visual_state[:total_visual_blocks]

        # Symbols - Using standard large square emojis to ensure consistent size and spacing
        SYM_DONE = "🟩" # Green Square
        SYM_SKIP = "🟦" # Blue Square (Updated from Orange)
        SYM_TODO = "⬜" # White Large Square

        # Construct the 2 rows string
        # Row 0: Even indices (0, 2, 4...)
        # Row 1: Odd indices (1, 3, 5...)
        # This creates a vertical-first fill (Top-Left, Bottom-Left, Top-Next...)
        
        # Added space after -# for correct Discord subscript formatting
        row0 = "-# "
        row1 = "-# "
        
        for i in range(total_visual_blocks):
            val = visual_state[i]
            if val == 1: sym = SYM_DONE
            elif val == 2: sym = SYM_SKIP
            else: sym = SYM_TODO
            
            if i % 2 == 0:
                row0 += sym
            else:
                row1 += sym
                
        return f"{row0}\n{row1}"

    async def update_message(self, interaction, finished=False, congratulation=None):
        # Line 1: User Mention with Count
        # Line 2: Geometric Bar (16x2)
        # Line 3: Buttons OR Congratulation Message
        
        completed_tasks = self.state.count(1) + self.state.count(2)
        content = f"<@{self.user_id}>'s tasks: {completed_tasks}/{self.total}\n{self.get_emoji_bar()}"
        
        if finished and congratulation:
            content += f"\n🎉 **{congratulation}**"
            view = None
        else:
            view = self

        if interaction:
            await interaction.response.edit_message(content=content, view=view)
        
        # DB Update
        if finished:
            await tasks_col.delete_one({"message_id": self.message_id})
        else:
            await self.update_db()

    async def update_db(self):
        if self.message_id:
            await tasks_col.update_one(
                {"message_id": self.message_id}, 
                {"$set": {"state": self.state}}
            )

    def get_next_index(self):
        try:
            return self.state.index(0)
        except ValueError:
            return -1

    async def check_completion(self, interaction):
        if 0 not in self.state:
            await self.finish_logic(interaction)
        else:
            await self.update_message(interaction)

    async def finish_logic(self, interaction):
        # 1. Convert remaining '0' (Todo) to '2' (Skipped)
        # Any task not explicitly 'done' is considered skipped for scoring.
        self.state = [2 if x == 0 else x for x in self.state]
        
        # 2. Calculate score (Only '1's count towards the percentage)
        greens = [x for x in self.state if x == 1]
        percent_complete = int((len(greens) / self.total) * 100)
        
        msg_key = "1"
        if 25 <= percent_complete < 50: msg_key = "2"
        elif 50 <= percent_complete < 75: msg_key = "3"
        elif 75 <= percent_complete: msg_key = "4"
        
        celebration = config_cache["celebratory_messages"].get(msg_key, "Good job!")
        
        await self.update_message(interaction, finished=True, congratulation=celebration)

    # --- BUTTONS ---
    # Labels added back, emojis removed
    
    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="bb_done")
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        
        idx = self.get_next_index()
        if idx == -1:
            return await self.finish_logic(interaction)

        self.history.append((idx, 0))
        self.state[idx] = 1 # Green (Done)
        await self.check_completion(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, custom_id="bb_skip") # Primary is Blue
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)

        idx = self.get_next_index()
        if idx == -1:
            return await self.finish_logic(interaction)

        self.history.append((idx, 0))
        self.state[idx] = 2 # Blue (Skipped)
        await self.check_completion(interaction)

    @discord.ui.button(label="Undo", style=discord.ButtonStyle.secondary, custom_id="bb_undo") # Secondary is Grey
    async def undo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)
        
        if not self.history:
            return await interaction.response.send_message("Nothing to undo!", ephemeral=True)

        last_idx, last_val = self.history.pop()
        self.state[last_idx] = last_val
        await self.update_message(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.blurple, custom_id="bb_finish") # Blurple is Purple-ish
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your list, buggy!", ephemeral=True)

        await self.finish_logic(interaction)


# --- 4 & 5. EVENTS ---

@bot.event
async def on_ready():
    await load_config()
    
    # Restore persistent views
    active_tasks = await tasks_col.find_all()
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
            
    print(f'BetterBuggy is ready! Logged in as {bot.user}')
    print(f'Restored {count} active task trackers.')

@bot.event
async def on_message(message):
    if message.author.bot: return

    # --- 1. SLEEP COMMANDS ---
    if bot.user in message.mentions:
        content = message.content.lower()
        
        # A. Self Commands
        if re.search(r"\bi'?m\s+(going\s+to\s+sleep|falling\s+asleep)", content):
            await handle_sleep_command(message, message.author)
            return
            
        # B. Target Commands
        targets = [m for m in message.mentions if m != bot.user]
        if targets and re.search(r"(is\s+asleep|is\s+sleeping|fell\s+asleep)", content):
            target = targets[0]
            if not message.author.voice or not target.voice or \
               message.author.voice.channel.id != target.voice.channel.id:
                return 
            
            await handle_sleep_command(message, target)
            return

    # --- 2. TASK COMMANDS ---
    if bot.user in message.mentions:
        text = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        
        if text.isdigit():
            num = int(text)
            if num > 100:
                await message.channel.send(f"{message.author.mention} That's too many tasks! Try 100 or less, buggy.")
                return
            if num < 1:
                return

            existing = await tasks_col.find_one({"user_id": message.author.id})
            if existing:
                # Check if the message still exists
                try:
                    channel_id = existing.get('channel_id')
                    msg_id = existing.get('message_id')
                    
                    message_exists = False
                    if channel_id:
                        try:
                            channel = bot.get_channel(channel_id)
                            if channel:
                                await channel.fetch_message(msg_id)
                                message_exists = True
                        except discord.NotFound:
                            pass # Message deleted
                        except discord.Forbidden:
                            pass # Can't see channel anymore
                            
                    if message_exists:
                        await message.channel.send(
                            f"{message.author.mention} You already have an active list! Please close it first.",
                            delete_after=5
                        )
                        return
                    else:
                        # Message doesn't exist (deleted), so remove DB entry and allow new one
                        await tasks_col.delete_one({"user_id": message.author.id})
                        
                except Exception as e:
                    print(f"Error checking existing task: {e}")
                    # Fallback: just delete it to prevent locking user out forever
                    await tasks_col.delete_one({"user_id": message.author.id})

            view = TaskView(user_id=message.author.id, total=num)
            msg = await message.channel.send(
                f"<@{message.author.id}>'s tasks: 0/{num}\n{view.get_emoji_bar()}",
                view=view
            )
            
            view.message_id = msg.id
            
            await tasks_col.insert_one({
                "user_id": message.author.id,
                "message_id": msg.id,
                "channel_id": message.channel.id, # Storing channel ID now!
                "total": num,
                "state": view.state
            })
            return

    await bot.process_commands(message)

async def handle_sleep_command(message, target_member):
    if not config_cache['sleep_vc_id']:
        await message.channel.send("❌ Sleep VC has not been set yet!")
        return

    if not target_member.voice:
        return

    sleep_channel = bot.get_channel(config_cache['sleep_vc_id'])
    if not sleep_channel:
        await message.channel.send("❌ Sleep VC channel not found (ID might be wrong).")
        return

    try:
        await target_member.move_to(sleep_channel)
        await message.add_reaction("💤")
        await message.add_reaction("🛌")
    except discord.Forbidden:
        await message.channel.send("❌ I don't have permission to move members, buggy!")
    except Exception as e:
        print(f"Failed to move user: {e}")

# --- 6. SETTINGS COMMANDS ---

@bot.command()
@commands.has_permissions(administrator=True)
async def setsleepvc(ctx, channel: discord.VoiceChannel):
    config_cache['sleep_vc_id'] = channel.id
    await config_col.update_one({"_id": "settings"}, {"$set": {"sleep_vc_id": channel.id}})
    await ctx.send(f"✅ Sleep VC set to {channel.name}.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setmessage(ctx, level: str, *, text: str):
    if level not in ["1", "2", "3", "4"]:
        await ctx.send("❌ Level must be 1, 2, 3, or 4.")
        return
    
    config_cache['celebratory_messages'][level] = text
    await config_col.update_one(
        {"_id": "settings"}, 
        {"$set": {"celebratory_messages": config_cache['celebratory_messages']}}
    )
    await ctx.send(f"✅ Message for Level {level} updated.")

@bot.command()
@commands.has_permissions(administrator=True)
async def settings(ctx):
    vc_id = config_cache.get('sleep_vc_id')
    vc_name = f"<#{vc_id}>" if vc_id else "Not Set"
    
    msgs = config_cache.get('celebratory_messages', {})
    
    txt = (
        f"**💤 Sleep VC:** {vc_name}\n\n"
        f"**🎉 Celebration Messages:**\n"
        f"Level 1 (0-24%): {msgs.get('1')}\n"
        f"Level 2 (25-49%): {msgs.get('2')}\n"
        f"Level 3 (50-74%): {msgs.get('3')}\n"
        f"Level 4 (75-100%): {msgs.get('4')}"
    )
    await ctx.send(txt)

bot.run(TOKEN)
