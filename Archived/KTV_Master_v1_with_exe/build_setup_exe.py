#!/usr/bin/env python3
"""Build setup_ktv.exe from setup_ktv.py using PyInstaller."""
import os, shutil
import PyInstaller.__main__

VR = r'C:\Users\user\Desktop\VR'
os.chdir(VR)

PyInstaller.__main__.run([
    '--onefile',
    '--windowed',
    '--name', 'setup_ktv',
    '--distpath', os.path.join(VR, 'dist_ktv'),
    'setup_ktv.py',
])
