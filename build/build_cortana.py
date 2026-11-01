"""Build dist/Cortana.exe (one file, windowed) from app/. Run on Windows:  python build/build_cortana.py

Needs: Python 3.11+ for Windows and the packages in requirements-build.txt (installed automatically if missing).
"""
from pathlib import Path
import importlib.util, os, subprocess, sys

root = Path(__file__).resolve().parent.parent
app, dist, work = root / 'app', root / 'dist', root / 'build' / 'work'
log = work / 'cortana-build.log'
work.mkdir(parents=True, exist_ok=True)

if os.name != 'nt':
    sys.exit('Build on Windows: Cortana.exe uses Windows speech, keyboard and process APIs.')

needed = {'PyInstaller': 'pyinstaller', 'qrcode': 'qrcode', 'dateutil': 'python-dateutil', 'tzdata': 'tzdata', 'pypdf': 'pypdf', 'sherpa_onnx': 'sherpa-onnx==2.0.1', 'numpy': 'numpy'}
missing = [pkg for mod, pkg in needed.items() if importlib.util.find_spec(mod) is None]
if missing:
    print('Installing', ', '.join(missing))
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *missing], check=True)

if not (app / 'assets' / 'cortana.glb').exists():
    print('WARNING: app/assets/cortana.glb is missing - the 3D character will not appear in this build.')

WEB_FILES = ['index.html', 'app.js', 'pages.js', 'avatar.js', 'responsive.css', 'mic-worklet.js', 'speech.ps1', 'manifest.webmanifest', 'app-icon.svg']
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--name', 'Cortana',
        '--distpath', str(dist), '--workpath', str(work / 'pyinstaller'), '--specpath', str(work), '--paths', str(app)]
for name in ['qrcode', 'store', 'tools', 'voice', 'hardware', 'files', 'pypdf', 'dateutil', 'dateutil.rrule', 'tzdata', 'neural', 'companion', 'lips', 'sherpa_onnx', 'numpy']:
    args += ['--hidden-import', name]
args += ['--collect-data', 'tzdata', '--collect-all', 'sherpa_onnx']
for name in ['PIL', 'torch', 'cv2', 'matplotlib', 'scipy', 'pandas']:
    args += ['--exclude-module', name]
for name in WEB_FILES:
    args += ['--add-data', str(app / name) + os.pathsep + '.']
for name in ['assets', 'vendor', 'voice-profile']:
    args += ['--add-data', str(app / name) + os.pathsep + name]
args += [str(app / 'launcher.py')]

with log.open('w') as f:
    p = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT)
print('BUILD_EXIT', p.returncode)
if p.returncode:
    print(log.read_text()[-2500:])
else:
    print('Built', dist / 'Cortana.exe')
sys.exit(p.returncode)
