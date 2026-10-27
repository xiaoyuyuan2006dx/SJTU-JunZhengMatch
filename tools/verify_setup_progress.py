"""Check the actual native dependency progress window, without network downloads."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
from junzheng_match.windows_setup import run_setup

user=ctypes.windll.user32
user.FindWindowW.restype=w.HWND
user.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR]
seen=threading.Event()
def observe():
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if user.FindWindowW(None,'正在准备独立窗口组件'):seen.set();return
        time.sleep(.05)
watcher=threading.Thread(target=observe,daemon=True);watcher.start()
run_setup([sys.executable,'-c','import time;time.sleep(2)'],timeout=10)
watcher.join(1)
assert seen.is_set(),'Dependency progress window was not displayed'
assert not user.FindWindowW(None,'正在准备独立窗口组件'),'Dependency progress window did not close'
try:run_setup([sys.executable,'-c','raise SystemExit(7)'],timeout=10)
except subprocess.CalledProcessError:pass
else:raise AssertionError('Setup failure must propagate')
result=dict(status='ok',visible_progress=True,closes_after_setup=True,setup_failure_reported=True)
Path('setup-progress-test.json').write_text(json.dumps(result),encoding='utf-8')
print(json.dumps(result))
