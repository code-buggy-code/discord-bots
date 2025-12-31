import os
import time
import sys
import datetime
import json
import urllib.request
import subprocess

# --- CONFIGURATION ---
DAILY_REPORT_HOUR = 4 # 4 AM
# ---------------------

ROOT_DIR = "/home/ubuntu/GitHub"
sys.path.append(ROOT_DIR)

# 1. Get Token (Try BuggyBot first)
try:
    from BuggyBot.secret_bot import TOKEN
except:
    TOKEN = None

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

# 2. Find the Log Channel (Reads BuggyBot's memory)
def get_log_channel_id():
    try:
        db_path = os.path.join(ROOT_DIR, "BuggyBot", "database.json")
        with open(db_path, "r") as f:
            data = json.load(f)
        config_list = data.get("bot_config", [])
        for doc in config_list:
            if doc.get("_id") == "config":
                return doc.get("log_channel_id")
    except: return None

# 3. Send to Discord
def send_discord_msg(content):
    channel_id = get_log_channel_id()
    if not TOKEN or not channel_id: return 
    
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    data = {"content": content} # Simple content for alerts
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        urllib.request.urlopen(req)
    except Exception as e:
        log(f"⚠️ Failed to send Discord log: {e}")

# 4. Check & Start Bots (The Watchdog)
def start_bots():
    active_bots = []
    
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        
        # Check for valid bot folders
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            
            # FULL PATH TRICK
            script_path = os.path.join(folder_path, "main.py")
            
            # Check if running using the specific path
            check = subprocess.getoutput(f"ps -ef | grep '{script_path}'")
            
            if script_path in check:
                active_bots.append(item)
            else:
                # IT CRASHED (or isn't running)! Restart it.
                log(f"⚠️ {item} is down! Restarting...")
                
                os.chdir(folder_path)
                os.system(f"nohup python3 {script_path} > ../{item}.log 2>&1 &")
                os.chdir(ROOT_DIR)
                
                # --- NOTIFY DISCORD ---
                send_discord_msg(f"⚠️ **Alert:** I had to restart **{item}**!")
                active_bots.append(item)
                
    return active_bots

# 5. Check for Local Changes (Auto-Upload)
def check_for_push():
    os.chdir(ROOT_DIR)
    # Check if there are modified files
    status = subprocess.getoutput("git status --porcelain")
    
    if status:
        log("💾 Local changes detected! Uploading to GitHub...")
        os.system("git add .")
        os.system('git commit -m "Auto-save by Manager"')
        os.system("git push")
        
        # --- NOTIFY DISCORD ---
        send_discord_msg("💾 **Backup:** I saved your latest code changes to GitHub.")

# --- MAIN LOOP ---
if __name__ == "__main__":
    log("✅ Chatty Manager Started.")
    # Send a wake-up message so you know it's working
    send_discord_msg("👀 **Manager Online:** Watching your bots now.")
    
    last_report_date = None

    while True:
        try:
            # 1. Watchdog
            bots = start_bots()

            # 2. Auto-Upload (Backups)
            check_for_push()

            # 3. Daily Report
            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                msg = f"🌞 **Daily Report**\nSystem is healthy.\nActive Bots: {', '.join(bots)}"
                send_discord_msg(msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(60) # Check every minute
