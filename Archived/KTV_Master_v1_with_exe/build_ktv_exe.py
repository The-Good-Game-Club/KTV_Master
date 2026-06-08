#!/usr/bin/env python3
"""Build KTV.exe from KTV_GUI.py (KTV.py stays separate)."""
import os, shutil
import PyInstaller.__main__

VR = r'C:\Users\user\Desktop\KTV_Master_v2'

# Clean old builds
for d in ['dist_ktv', 'build']:
    p = os.path.join(VR, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
for f in ['KTV.spec', 'setup_ktv.spec']:
    p = os.path.join(VR, f)
    if os.path.isfile(p):
        os.remove(p)

args = [
    '--onefile',
    '--windowed',
    '--name', 'KTV',
    '--distpath', os.path.join(VR, 'dist_ktv'),
    os.path.join(VR, 'KTV_GUI.py'),
]

PyInstaller.__main__.run(args)
