"""
Runs both Telegram bots in parallel threads.
"""
import subprocess, sys, threading, os

def run(script):
    print(f"[run_bots] starting {script}", flush=True)
    proc = subprocess.Popen(
        [sys.executable, '-u', script],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    proc.wait()
    print(f"[run_bots] {script} exited with code {proc.returncode}", flush=True)

threads = [threading.Thread(target=run, args=(b,), daemon=False)
           for b in ['telegram_bot.py', 'campaigns_bot.py']]
for t in threads:
    t.start()
for t in threads:
    t.join()
