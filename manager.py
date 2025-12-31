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
    queue = []
    if os.path.exists(IPC_FILE):
        try:
            with open(IPC_FILE, "r") as f:
                queue = json.load(f)
        except: queue = []
    
    queue.append(content)
    
    with open(IPC_FILE, "w") as f:
        json.dump(queue, f)

# 2. Start Bots (The Watchdog)
def start_all_bots():
    active_bots = []
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            
            # 1. Calculate the FULL PATH
            script_path = os.path.join(folder_path, "main.py")
            
            # 2. Check if the FULL PATH is running (Ignore the grep command itself)
            check = subprocess.getoutput(f"ps -ef | grep '{script_path}' | grep -v grep")
            
            if check:
                active_bots.append(item)
            else:
                # 3. Start using the FULL PATH (The Fix!)
                log(f"⚡ (Re)starting {item}...")
                os.chdir(folder_path)
                # We use {script_path} here so the process list shows the full name
                os.system(f"nohup python3 {script_path} > ../{item}.log 2>&1 &")
                active_bots.append(item)
                os.chdir(ROOT_DIR)
            
    return active_bots

# 3. Check for Local Changes (Quiet Backup)
def check_for_push():
    os.chdir(ROOT_DIR)
    status = subprocess.getoutput("git status --porcelain")
    
    if status:
        log("💾 Local changes detected. Backing up to GitHub (Quietly)...")
        os.system("git add .")
        os.system('git commit -m "Auto-sync by Manager"')
        os.system("git push")

# --- MAIN LOOP ---
if __name__ == "__main__":
    # Kill old processes so we can start fresh with full paths
    os.system("pkill -f main.py")
    time.sleep(2)
    
    bots = start_all_bots()
    log(f"✅ Fixed Manager Started. Active: {', '.join(bots)}")
    queue_discord_msg(f"👀 **Manager Online:** Loop fixed! I am tracking full paths now.")
    
    last_report_date = None

    while True:
        try:
            bots = start_all_bots()
            check_for_push()

            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nSystem is healthy."
                queue_discord_msg(status_msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(60)
