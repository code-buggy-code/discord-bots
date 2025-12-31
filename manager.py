import os
import time
import subprocess
import sys
import datetime
import json

# --- CONFIGURATION ---
DAILY_REPORT_HOUR = 4 # 4 AM
# ---------------------

ROOT_DIR = "/home/ubuntu/GitHub"
sys.path.append(ROOT_DIR)

# Path to the shared "Mailbox" file
IPC_FILE = os.path.join(ROOT_DIR, "BuggyBot", "pending_logs.json")

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

# 1. WRITE to the Mailbox (Hand log to BuggyBot)
def queue_discord_msg(content):
    # Load existing queue
    queue = []
    if os.path.exists(IPC_FILE):
        try:
            with open(IPC_FILE, "r") as f:
                queue = json.load(f)
        except: queue = []
    
    # Add new message
    queue.append(content)
    
    # Save back to file
    with open(IPC_FILE, "w") as f:
        json.dump(queue, f)

# 2. Start Bots (The Watchdog)
def start_bots():
    active_bots = []
    
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            
            # FULL PATH TRICK
            script_path = os.path.join(folder_path, "main.py")
            
            # Check if running
            check = subprocess.getoutput(f"ps -ef | grep '{script_path}'")
            
            if script_path in check:
                active_bots.append(item)
            else:
                # IT CRASHED! Restart it.
                log(f"⚠️ {item} is down! Restarting...")
                
                os.chdir(folder_path)
                os.system(f"nohup python3 {script_path} > ../{item}.log 2>&1 &")
                os.chdir(ROOT_DIR)
                
                # Hand the log to BuggyBot (via file)
                queue_discord_msg(f"⚠️ **Manager Alert:** I had to restart **{item}**!")
                active_bots.append(item)
                
    return active_bots

# 3. Check for Local Changes (Auto-Upload)
def check_for_push():
    os.chdir(ROOT_DIR)
    status = subprocess.getoutput("git status --porcelain")
    
    if status:
        log("💾 Local changes detected! Uploading to GitHub...")
        os.system("git add .")
        os.system('git commit -m "Auto-save by Manager"')
        os.system("git push")
        
        queue_discord_msg("💾 **Backup:** I saved your latest code changes to GitHub.")

# --- MAIN LOOP ---
if __name__ == "__main__":
    log("✅ Messenger Manager Started.")
    queue_discord_msg("👀 **Manager Online:** I will hand logs to BuggyBot.")
    
    last_report_date = None

    while True:
        try:
            bots = start_bots()
            check_for_push()

            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                msg = f"🌞 **Daily Report**\nSystem is healthy.\nActive Bots: {', '.join(bots)}"
                queue_discord_msg(msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(60)
