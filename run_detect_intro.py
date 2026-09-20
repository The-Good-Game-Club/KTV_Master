#!/usr/bin/env python3
"""Same path-cleaning as run_ktv_clean.py, then run detect_intro.py"""
import sys
import site

# Strip Hermes venv paths
user_sp = site.getusersitepackages()
if user_sp and user_sp not in sys.path:
    sys.path.insert(0, user_sp)

sys.path = [p for p in sys.path if 'hermes' not in str(p).lower()]

# Also add python3.13 site-packages explicitly
import subprocess
result = subprocess.run([sys.executable, '-c', 'import site; print(site.getusersitepackages())'],
                       capture_output=True, text=True)
correct_sp = result.stdout.strip()
if correct_sp and correct_sp not in sys.path:
    sys.path.insert(0, correct_sp)

# Now run the detection
exec(open(r"C:\Users\user\Desktop\KTV_Master_v2\detect_intro.py", encoding='utf-8').read(), {'__name__': '__main__'})
