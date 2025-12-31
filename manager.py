import os
import time
import subprocess
import sys
import datetime
import json
import signal

# --- CONFIGURATION ---
DAILY_REPORT_HOUR = 4 # 4 AM
# ---------------------

ROOT_DIR = "/home/ubuntu/GitHub"
sys.path.append(ROOT_DIR)

# Path to the shared "Mailbox" file
IPC_FILE = os.path.join(ROOT_DIR, "BuggyBot", "pending_logs.json")

# Memory to remember when files were last changed
bot_timestamps = {}

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

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

def get_file_mtime(filepath):
    """Gets the 'modification time' of a file to see if it changed."""
    try:
        return os.path.getmtime(filepath)
    except:
        return 0

def kill_bot(script_path):
    """Finds and stops a specific bot."""
    # Find the Process ID (PID)
    pid_cmd = f"ps -ef | grep '{script_path}' | grep -v grep | awk '{{print $2}}'"
    pids = subprocess.getoutput(pid_cmd).split()
    
    for pid in pids:
        if pid:
            try:
                os.kill(int(pid), signal.SIGKILL)
                log(f"🔫 Killed old process: {pid}")
            except:
                pass

def manage_bots():
    active_bots = []
    
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        
        # We only care about folders with "main.py"
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            script_path = os.path.join(folder_path, "main.py")
            current_mtime = get_file_mtime(script_path)
            
            # CHECK 1: Is the bot running?
            is_running = subprocess.getoutput(f"ps -ef | grep '{script_path}' | grep -v grep")
            
            # CHECK 2: Did the code change?
            last_mtime = bot_timestamps.get(item, 0)
            code_changed = (last_mtime != 0) and (current_mtime > last_mtime)
            
            if code_changed:
                log(f"🔄 Update detected for {item}! Restarting...")
                kill_bot(script_path)
                is_running = False # Force restart
            
            if not is_running:
                log(f"⚡ Starting {item}...")
                os.chdir(folder_path)
                os.system(f"nohup python3 {script_path} > ../{item}.log 2>&1 &")
                os.chdir(ROOT_DIR)
                
            # Update our memory
            bot_timestamps[item] = current_mtime
            active_bots.append(item)
            
    return active_bots

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
    # Clean slate on startup!
    log("🧹 Cleaning up old bots...")
    os.system("pkill -f main.py")
    time.sleep(2)
    
    bots = manage_bots()
    log(f"✅ Smart Manager Started. Active: {', '.join(bots)}")
    queue_discord_msg(f"👀 **Smart Manager Online:** I am watching for code changes!")
    
    last_report_date = None

    while True:
        try:
            bots = manage_bots() # Checks for updates every loop!
            check_for_push()

            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nSystem is healthy."
                queue_discord_msg(status_msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(10) # Check faster (every 10 seconds)
