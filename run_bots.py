"""
Runs both Telegram bots in parallel threads.
"""
import threading, subprocess, sys, os

bots = ['telegram_bot.py', 'campaigns_bot.py']

def run(script):
    subprocess.run([sys.executable, script], cwd=os.path.dirname(os.path.abspath(__file__)))

threads = [threading.Thread(target=run, args=(b,), daemon=False) for b in bots]
for t in threads:
    t.start()
for t in threads:
    t.join()
