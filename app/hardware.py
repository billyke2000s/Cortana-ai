"""Hardware detection and AI model recommendations.

Detects graphics memory (nvidia-smi, then the Windows display-adapter registry, which also covers AMD/Intel) and system
RAM, then rates each Qwen 3.5 model for this PC: which one to recommend, which work, and which are too big to select.

Ratings (dense models), using usable VRAM = total VRAM - 1.5 GB for Windows and the browser:
  fast     the whole model fits on the GPU
  good     at least 80% fits (small slowdown; e.g. 9B on an 8 GB RTX 3070 measured ~21 tokens/s)
  slow     at least 60% fits (noticeably slower; allowed with a warning)
  too_big  less than that, or not enough system RAM: cannot be selected
Mixture-of-experts models only run ~3B parameters per token, so they stay usable with 35% on the GPU.
"""
import ctypes, os, shutil, subprocess

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
WINDOWS_RESERVE_GB = 1.5      # desktop, browser and Cortana's own page use this much graphics memory
OVERHEAD_GB = 0.3             # context cache at 6,144 tokens on top of the file size (measured on the 9B)

# Ollama download sizes (default quantisation), measured from `ollama list`; the 35B MoE size is the 4-bit total from
# Unsloth's Qwen 3.5 guide. 'quality' orders models from least to most capable.
CATALOG = [
    {'tag': 'qwen3.5:0.8b', 'label': 'Qwen 3.5 0.8B', 'size_gb': 1.0, 'quality': 1, 'moe': False, 'blurb': 'Tiny. Quick replies, weak reasoning.'},
    {'tag': 'qwen3.5:2b', 'label': 'Qwen 3.5 2B', 'size_gb': 2.7, 'quality': 2, 'moe': False, 'blurb': 'Light. Fine for simple chat and timers.'},
    {'tag': 'qwen3.5:4b', 'label': 'Qwen 3.5 4B', 'size_gb': 3.4, 'quality': 3, 'moe': False, 'blurb': 'Fast and capable. Good tool use.'},
    {'tag': 'qwen3.5:9b', 'label': 'Qwen 3.5 9B', 'size_gb': 6.6, 'quality': 4, 'moe': False, 'blurb': 'Smart all-rounder. Best for 8-12 GB cards.'},
    {'tag': 'qwen3.5:35b-a3b', 'label': 'Qwen 3.5 35B-A3B (MoE)', 'size_gb': 22.0, 'quality': 5, 'moe': True, 'blurb': 'Large mixture-of-experts. Fast for its size; needs lots of memory.'},
    {'tag': 'qwen3.5:27b', 'label': 'Qwen 3.5 27B', 'size_gb': 17.4, 'quality': 6, 'moe': False, 'blurb': 'Smartest dense model. Needs a 20 GB+ card.'},
]


def _nvidia():
    exe = shutil.which('nvidia-smi') or (r'C:\Windows\System32\nvidia-smi.exe' if os.path.exists(r'C:\Windows\System32\nvidia-smi.exe') else None)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=10, creationflags=HIDDEN).stdout
        gpus = [(n.strip(), float(m) / 1024) for n, m in (line.rsplit(',', 1) for line in out.strip().splitlines() if ',' in line)]
        return max(gpus, key=lambda g: g[1]) if gpus else None
    except Exception:
        return None


def _registry():
    """Dedicated video memory from the display-adapter registry keys (64-bit value, works for NVIDIA/AMD/Intel)."""
    if os.name != 'nt':
        return None
    import winreg
    best = None
    base = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return None
    for i in range(64):
        try:
            name = winreg.EnumKey(root, i)
        except OSError:
            break
        try:
            with winreg.OpenKey(root, name) as key:
                size = winreg.QueryValueEx(key, 'HardwareInformation.qwMemorySize')[0]
                desc = winreg.QueryValueEx(key, 'DriverDesc')[0]
        except OSError:
            continue
        gb = int(size) / 1024 ** 3
        if gb >= 0.5 and (not best or gb > best[1]):
            best = (str(desc), gb)
    return best


def _ram_gb():
    if os.name == 'nt':
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        s = MEMORYSTATUSEX(); s.dwLength = ctypes.sizeof(s)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return s.ullTotalPhys / 1024 ** 3
    try:
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 16.0


def detect():
    """{'gpu': name|None, 'vram_gb': float|None, 'ram_gb': float, 'source': str}. CORTANA_FAKE_VRAM_GB/RAM_GB override (tests)."""
    if os.getenv('CORTANA_FAKE_VRAM_GB') is not None:
        v = float(os.environ['CORTANA_FAKE_VRAM_GB'])
        return {'gpu': 'Test GPU' if v else None, 'vram_gb': v or None, 'ram_gb': float(os.getenv('CORTANA_FAKE_RAM_GB', '16')), 'source': 'override'}
    gpu, source = _nvidia(), 'nvidia-smi'
    if not gpu:
        gpu, source = _registry(), 'registry'
    return {'gpu': gpu[0] if gpu else None, 'vram_gb': round(gpu[1], 1) if gpu else None, 'ram_gb': round(_ram_gb(), 1),
            'source': source if gpu else 'none'}


def rate(model, hw):
    """Rate one catalog entry for this hardware."""
    need = model['size_gb'] + OVERHEAD_GB
    ram_free = max(0.0, hw['ram_gb'] - 6.0)          # leave room for Windows and apps
    vram = hw.get('vram_gb')
    if not vram:                                    # CPU only
        if model['size_gb'] <= 3.5 and need <= ram_free:
            return 'slow', 0, 'No graphics card detected: runs on the processor, expect slow replies.'
        return 'too_big', 0, 'Too large to run without a graphics card.'
    usable = max(0.0, vram - WINDOWS_RESERVE_GB)
    frac = min(1.0, usable / need)
    spill = max(0.0, need - usable)
    if spill > ram_free:
        return 'too_big', round(frac * 100), f'Needs about {need:.0f} GB; not enough graphics memory + RAM.'
    if model['moe']:
        if frac >= .35:
            return ('fast' if frac >= 1 else 'good'), round(frac * 100), 'Mixture-of-experts: stays quick even when partly on the processor.'
        return 'too_big', round(frac * 100), f'Needs about {need:.0f} GB; too little of it would fit on the graphics card.'
    if frac >= 1:
        return 'fast', 100, 'Fits entirely on your graphics card.'
    if frac >= .80:
        return 'good', round(frac * 100), f'About {frac * 100:.0f}% fits on the graphics card; a small slowdown.'
    if frac >= .60:
        return 'slow', round(frac * 100), f'Only about {frac * 100:.0f}% fits on the graphics card; noticeably slower.'
    return 'too_big', round(frac * 100), f'Needs about {need:.0f} GB of graphics memory; your card has {vram:.0f} GB.'


def recommend(hw, installed=(), available=None):
    """Rate every model and pick the most capable one that runs fast or well. `available` limits the list to tags that exist."""
    rows = []
    for m in CATALOG:
        if available is not None and m['tag'] not in available:
            continue
        rating, gpu_pct, note = rate(m, hw)
        rows.append({**m, 'rating': rating, 'gpu_pct': gpu_pct, 'note': note, 'selectable': rating != 'too_big',
                     'installed': m['tag'] in installed, 'recommended': False})
    if hw.get('vram_gb'):
        good = [r for r in rows if r['rating'] in ('fast', 'good') and not r['moe']] or [r for r in rows if r['rating'] in ('fast', 'good')]
    else:
        good = [r for r in rows if r['tag'] == 'qwen3.5:2b' and r['selectable']] or [r for r in rows if r['selectable']]
    if good:
        max(good, key=lambda r: r['quality'])['recommended'] = True
    return rows


def recommended_tag(rows, fallback='qwen3.5:4b'):
    return next((r['tag'] for r in rows if r['recommended']), fallback)


def models_dir():
    return os.environ.get('OLLAMA_MODELS') or os.path.join(os.path.expanduser('~'), '.ollama', 'models')


def free_disk_gb(path=None):
    path = path or models_dir()
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        return shutil.disk_usage(path or os.path.expanduser('~')).free / 1024 ** 3
    except OSError:
        return None
