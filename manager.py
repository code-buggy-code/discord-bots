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

# 1. Get the Secret Token from BUGGYBOT (The Boss)
try:
    from BuggyBot.secret_bot import TOKEN
except:
    TOKEN = None

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

# 2. Get the Log Channel from BUGGYBOT'S database
def get_log_channel_id():
    try:
        # Look in BuggyBot folder
        db_path = os.path.join(ROOT_DIR, "BuggyBot", "database.json")
        with open(db_path, "r") as f:
            data = json.load(f)
        
        # Look for 'bot_config' (BuggyBot's schema)
        config_list = data.get("bot_config", [])
        for doc in config_list:
            if doc.get("_id") == "config":
                # Look for 'log_channel_id' (BuggyBot's key name)
                return doc.get("log_channel_id")
    except:
        return None
    return None

# 3. Send to Discord
def send_discord_msg(content):
    channel_id = get_log_channel_id()
    
    if not TOKEN or not channel_id:
        return 
    
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    
    data = {"content": f"📋 **Manager Report**\n```{content[:1900]}```"}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        urllib.request.urlopen(req)
    except Exception as e:
        log(f"⚠️ Failed to send Discord log: {e}")

# 4. Check & Start Bots
def start_all_bots():
    log("🔌 (Re)starting the bot family...")
    os.system("pkill -f main.py")
    time.sleep(2)

    active_bots = []
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            os.chdir(folder_path)
            # Use nohup to keep them alive
            os.system(f"nohup python3 main.py > ../{item}.log 2>&1 &")
            active_bots.append(item)
            os.chdir(ROOT_DIR)
            
    return active_bots

# 5. Check for Cloud Updates
def check_for_pull():
    os.chdir(ROOT_DIR)
    os.system("git fetch")
    status = subprocess.getoutput("git status")
    if "Your branch is behind" in status:
        log("🚀 Update found on GitHub! Downloading...")
        os.system("git pull")
        return True 
    return False

# 6. Check for Local Changes
def check_for_push():
    os.chdir(ROOT_DIR)
    status = subprocess.getoutput("git status --porcelain")
    
    if status:
        log("💾 Local changes detected! Syncing to GitHub...")
        os.system("git add .")
        os.system('git commit -m "Auto-sync by Manager"')
        os.system("git push")
        return True 
    return False

# --- MAIN LOOP ---
if __name__ == "__main__":
    bots = start_all_bots()
    log(f"✅ Manager Started (Using BuggyBot Identity). Active: {', '.join(bots)}")
    
    # Try to send a test message right away to verify permission
    send_discord_msg("👀 **Manager Online:** I am using BuggyBot's credentials now!")
    
    last_report_date = None

    while True:
        try:
            restart_needed = False
            
            if check_for_pull():
                log("📥 Pulled updates from cloud.")
                restart_needed = True
            
            if check_for_push():
                log("📤 Pushed local changes to cloud.")
                restart_needed = True
            
            if restart_needed:
                bots = start_all_bots()
                send_discord_msg(f"♻️ System synced and bots restarted.\nActive: {', '.join(bots)}")

            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nSystem is healthy."
                send_discord_msg(status_msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(60)
