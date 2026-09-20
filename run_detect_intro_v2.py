#!/usr/bin/env python3
"""Path-cleaned runner for detect_intro_v2.py"""
import sys, site, os

# Strip Hermes venv paths
sys.path = [p for p in sys.path if 'hermes' not in str(p).lower()]

# Find correct user site-packages for python3.13
import subprocess
result = subprocess.run([sys.executable, '-c', 'import site; print(site.getusersitepackages())'],
                       capture_output=True, text=True)
correct_sp = result.stdout.strip()
if correct_sp and correct_sp not in sys.path:
    sys.path.insert(0, correct_sp)

# Also set environment
os.environ['PYTHONPATH'] = correct_sp

script = r"C:\Users\user\Desktop\KTV_Master_v2\detect_intro_v2.py"
exec(open(script, encoding='utf-8').read(), {'__name__': '__main__'})
