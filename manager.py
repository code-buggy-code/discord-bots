import os
import time
import subprocess
import sys
import datetime
import json
import urllib.request

# --- CONFIGURATION ---
DAILY_REPORT_HOUR = 4 # 4 AM
# ---------------------

ROOT_DIR = "/home/ubuntu/GitHub"
sys.path.append(ROOT_DIR)

# 1. Get the Secret Token
try:
    from BuggyBot.secret_bot import TOKEN
except:
    TOKEN = None

# 2. Get the Log Channel from BuggyBot's memory
def get_log_channel_id():
    try:
        db_path = os.path.join(ROOT_DIR, "BuggyBot", "database.json")
        with open(db_path, "r") as f:
            data = json.load(f)
        
        config_list = data.get("bot_config", [])
        for doc in config_list:
            if doc.get("_id") == "config":
                return doc.get("log_channel_id")
    except:
        return None
    return None

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

def send_discord_msg(content):
    channel_id = get_log_channel_id()
    
    if not TOKEN or not channel_id:
        return 
    
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    
    data = {"content": f"📋 **Daily Server Report**\n```{content[:1900]}```"}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        urllib.request.urlopen(req)
    except Exception as e:
        log(f"⚠️ Failed to send Discord log: {e}")

def start_all_bots():
    log("🔌 Starting up the bot family...")
    os.system("pkill -f main.py")
    time.sleep(2)

    active_bots = []
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            os.chdir(folder_path)
            # Normal launch command since they have their own keys now
            os.system(f"nohup python3 main.py > ../{item}.log 2>&1 &")
            active_bots.append(item)
            os.chdir(ROOT_DIR)
            
    return active_bots

def check_for_updates():
    os.chdir(ROOT_DIR)
    os.system("git fetch")
    status = subprocess.getoutput("git status")
    if "Your branch is behind" in status:
        log("🚀 Update found! Downloading...")
        os.system("git pull")
        log("♻️ Restarting bots to apply update...")
        start_all_bots()

# --- MAIN LOOP ---
if __name__ == "__main__":
    bots = start_all_bots()
    log(f"✅ Manager Started. Active bots: {', '.join(bots)}")
    
    last_report_date = None

    while True:
        try:
            check_for_updates()
            
            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nSystem is healthy."
                send_discord_msg(status_msg)
                log("✅ Sent daily report to Discord.")
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Error: {e}")
        
        time.sleep(60)
