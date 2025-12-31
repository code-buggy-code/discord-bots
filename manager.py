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

# Try to get token for logs
try:
    from BadBug.secret_bot import TOKEN
except:
    TOKEN = None

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

def get_log_channel_id():
    # Tries to find BadBug's log channel setting
    try:
        db_path = os.path.join(ROOT_DIR, "BadBug", "database.json")
        with open(db_path, "r") as f:
            data = json.load(f)
        config_list = data.get("badbug_config", [])
        for doc in config_list:
            if doc.get("_id") == "settings":
                return doc.get("log_channel")
    except: return None

def send_discord_msg(content):
    channel_id = get_log_channel_id()
    if not TOKEN or not channel_id: return 
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    data = {"content": f"📋 **Manager Report**\n{content[:1900]}"}
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        urllib.request.urlopen(req)
    except: pass

def start_bots():
    log("🔌 Starting bots...")
    active_bots = []
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        # We look for folders containing main.py
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            # Check if this specific bot is ALREADY running to avoid double-starts
            # We use 'grep' to look for the folder name in the running process list
            check = subprocess.getoutput(f"ps -ef | grep 'python3 main.py' | grep '{item}'")
            
            if item in check:
                # It's already running, skip it
                active_bots.append(item)
            else:
                # It's dead, start it
                os.chdir(folder_path)
                os.system(f"nohup python3 main.py > ../{item}.log 2>&1 &")
                active_bots.append(item)
                log(f"   -> Started {item}")
                os.chdir(ROOT_DIR)
    return active_bots

# --- MAIN LOOP ---
if __name__ == "__main__":
    log("✅ Watchdog Manager Started.")
    last_report_date = None

    while True:
        try:
            # 1. Ensure bots are alive
            bots = start_bots()

            # 2. Daily Report
            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                send_discord_msg(f"🌞 **Good Morning!**\nSystem is healthy.\nActive Bots: {', '.join(bots)}")
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        # Wait 10 seconds before checking again (Fast recovery!)
        time.sleep(10)
