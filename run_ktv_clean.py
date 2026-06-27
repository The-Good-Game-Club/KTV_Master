"""KTV launcher - runs with isolated Python path, stripping Hermes venv"""
import sys
import os

# Remove ALL Hermes-related paths
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]

# Ensure the correct site-packages are findable
user_sp = r'C:\Users\user\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages'
if user_sp not in sys.path:
    sys.path.insert(0, user_sp)

# Change to KTV directory
ktv_dir = r'C:\Users\user\Desktop\KTV_Master_v2'
os.chdir(ktv_dir)

# Run KTV.py with the original command-line args
sys.argv = ['KTV.py'] + sys.argv[1:]  # strip launcher name, keep original args

# exec the file - this bypasses the __name__ guard issue
filepath = os.path.join(ktv_dir, 'KTV.py')
with open(filepath, encoding='utf-8') as f:
    code = compile(f.read(), filepath, 'exec')
exec(code, {'__name__': '__main__', '__file__': filepath})
