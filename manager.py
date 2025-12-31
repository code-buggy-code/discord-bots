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

# 3. Check for Cloud Updates
def check_for_pull():
    os.chdir(ROOT_DIR)
    os.system("git fetch")
    status = subprocess.getoutput("git status")
    if "Your branch is behind" in status:
        log("🚀 Update found on GitHub! Downloading...")
        os.system("git pull")
        return True 
    return False

# 4. Check for Local Changes
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
    # Start bots immediately
    bots = start_all_bots()
    log(f"✅ Mailbox Manager Started. Active: {', '.join(bots)}")
    queue_discord_msg(f"👀 **Manager Online:** I am using the Mailbox system now!")
    
    last_report_date = None

    while True:
        try:
            restart_needed = False
            
            if check_for_pull():
                log("📥 Pulled updates from cloud.")
                restart_needed = True
            
            # We catch push errors so the bot doesn't crash if git gets messy
            try:
                if check_for_push():
                    log("📤 Pushed local changes to cloud.")
                    restart_needed = True
            except: pass

            if restart_needed:
                bots = start_all_bots()
                queue_discord_msg(f"♻️ System synced and bots restarted.\nActive: {', '.join(bots)}")

            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nSystem is healthy."
                queue_discord_msg(status_msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(60)
