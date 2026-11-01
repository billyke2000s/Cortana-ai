"""Full access mode (1.7, owner request, D-038): run PowerShell commands and use the mouse and keyboard.

Off by default (setting `full_access`), PC-only (never from a paired phone), and every action is approved first:
- run_command: the exact command is shown on the approval card; it runs once, hidden, with a time limit.
- computer_task: the goal is approved once; then up to MAX_STEPS rounds of screenshot -> the local model picks ONE
  action -> it is performed. Emergency stop: push the mouse into the top-left corner, or Stop on the card.
Everything run is appended to DATA/full-access.log so the owner can see exactly what happened.
"""
import base64, ctypes, json, os, re, struct, subprocess, time
from datetime import datetime

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MAX_STEPS = 15
COMMAND_SECONDS = 120


def log(kind, text):
    from runtime import DATA
    try:
        with open(DATA / 'full-access.log', 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {kind}: {text}\n")
    except OSError:
        pass


# ------------------------------------------------------------------ run_command
def command_args(args):
    command = str(args.get('command') or '').strip()
    if not command:
        raise ValueError('There is no command to run.')
    if len(command) > 2000:
        raise ValueError('That command is too long.')
    return command, ' '.join(str(args.get('why') or '').split())[:200]


def preview_command(args):
    command, why = command_args(args)
    return {'summary': 'Run this PowerShell command on your PC' + (f' ({why})' if why else ''), 'detail': command}


def run_command(args):
    if os.name != 'nt':
        raise RuntimeError('Commands only run on the Windows PC.')
    command, _ = command_args(args)
    log('command', command)
    try:
        p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command],
                           capture_output=True, timeout=COMMAND_SECONDS, creationflags=HIDDEN, cwd=os.path.expanduser('~'))
    except subprocess.TimeoutExpired:
        log('result', f'timed out after {COMMAND_SECONDS}s')
        return {'error': f'The command was stopped after {COMMAND_SECONDS} seconds.'}
    out = p.stdout.decode('utf-8', 'replace').strip()
    err = p.stderr.decode('utf-8', 'replace').strip()
    log('result', f'exit {p.returncode}; {len(out)} chars out; {len(err)} chars error')
    result = {'exit_code': p.returncode, 'output': out[-2500:] or '(no output)'}
    if err:
        result['errors'] = err[-800:]
    if len(out) > 2500:
        result['note'] = 'Only the last 2,500 characters of the output are shown.'
    return result


# ------------------------------------------------------------------ mouse and keyboard (Windows SendInput, no extra packages)
VK = {'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B, 'windows': 0x5B, 'enter': 0x0D, 'return': 0x0D,
      'tab': 0x09, 'esc': 0x1B, 'escape': 0x1B, 'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E, 'space': 0x20, 'up': 0x26,
      'down': 0x28, 'left': 0x25, 'right': 0x27, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
      'playpause': 0xB3, 'next': 0xB0, 'previous': 0xB1, 'volumeup': 0xAF, 'volumedown': 0xAE, 'mute': 0xAD,
      **{f'f{i}': 0x6F + i for i in range(1, 13)}}
VK.update({c: ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'})
EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2E, 0x5B}


def parse_keys(keys):
    parts = [k.strip().lower() for k in re.split(r'\s*\+\s*', str(keys or '')) if k.strip()]
    if not parts or len(parts) > 4 or any(k not in VK for k in parts):
        raise ValueError(f'Unknown key combination: {keys}')
    return [VK[k] for k in parts]


class _Input:
    """Lazily built ctypes structures for SendInput (Windows only)."""
    built = None

    @classmethod
    def get(cls):
        if cls.built:
            return cls.built
        from ctypes import wintypes
        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('u', _U)]
        cls.built = (INPUT, MOUSEINPUT, KEYBDINPUT)
        return cls.built


def _send(*items):
    INPUT = _Input.get()[0]
    arr = (INPUT * len(items))(*items)
    ctypes.windll.user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    INPUT, MOUSEINPUT, _ = _Input.get()
    i = INPUT(type=0);i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0);return i


def _key(vk, up=False, unicode_char=None):
    INPUT, _, KEYBDINPUT = _Input.get()
    i = INPUT(type=1)
    if unicode_char is not None:
        i.u.ki = KEYBDINPUT(0, ord(unicode_char), 0x0004 | (0x0002 if up else 0), 0, 0)
    else:
        i.u.ki = KEYBDINPUT(vk, 0, (0x0002 if up else 0) | (0x0001 if vk in EXTENDED else 0), 0, 0)
    return i


def cursor_in_corner():
    """The emergency stop: the real mouse pushed into the top-left corner."""
    if os.name != 'nt':
        return False
    from ctypes import wintypes
    pt = wintypes.POINT();ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x <= 2 and pt.y <= 2


def perform(step, size):
    """Do one action. Coordinates are pixels in the screenshot of `size` (w, h); SendInput gets 0-65535 absolute values,
    so screen scaling (DPI) does not matter."""
    action = step.get('action')
    if action in ('click', 'double_click', 'right_click', 'move'):
        w, h = size
        x, y = float(step.get('x', -1)), float(step.get('y', -1))
        if not (0 <= x <= w and 0 <= y <= h):
            raise ValueError('That point is outside the screen.')
        ax, ay = int(x / w * 65535), int(y / h * 65535)
        _send(_mouse(0x0001 | 0x8000, ax, ay))   # MOVE | ABSOLUTE
        time.sleep(.08)
        if action == 'move':
            return
        down, up = (0x0008, 0x0010) if action == 'right_click' else (0x0002, 0x0004)
        for _ in range(2 if action == 'double_click' else 1):
            _send(_mouse(down), _mouse(up));time.sleep(.06)
    elif action == 'type':
        text = str(step.get('text') or '')[:500]
        for ch in text:
            if ch == '\n':
                _send(_key(0x0D), _key(0x0D, True))
            else:
                _send(_key(0, unicode_char=ch), _key(0, True, unicode_char=ch))
            time.sleep(.01)
    elif action == 'press':
        vks = parse_keys(step.get('keys'))
        _send(*[_key(v) for v in vks]);time.sleep(.05);_send(*[_key(v, True) for v in reversed(vks)])
    elif action == 'scroll':
        amount = max(-20, min(20, int(step.get('amount', -3))))
        _send(_mouse(0x0800, data=amount * 120))
    elif action == 'wait':
        time.sleep(min(5.0, max(.2, float(step.get('seconds', 1)))))
    else:
        raise ValueError(f'Unknown action {action}.')


# ------------------------------------------------------------------ the computer-use loop
SCREEN_PS = r'''
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -Namespace W -Name D -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][W.D]::SetProcessDPIAware()
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$full = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($full); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); $g.Dispose()
$scale = [Math]::Min(1.0, 1280 / $b.Width)
$out = New-Object System.Drawing.Bitmap ([int]($b.Width * $scale)), ([int]($b.Height * $scale))
$g = [System.Drawing.Graphics]::FromImage($out); $g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($full, 0, 0, $out.Width, $out.Height); $g.Dispose()
$out.Save($env:CORTANA_IMAGE_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
'''


def png_size(b64):
    raw = base64.b64decode(b64[:64] + '=' * (-len(b64[:64]) % 4))
    return struct.unpack('>II', raw[16:24])


def screen():
    import files
    shot = files._powershell_image(SCREEN_PS)
    return shot, png_size(shot)


PROMPT = ('You are operating this Windows PC with the mouse and keyboard to do this for the user: {goal}\n'
          'The image is the whole screen, {w}x{h} pixels. Steps so far:\n{history}\n'
          'Reply with ONE JSON object and nothing else, choosing the single next step:\n'
          '{{"action":"click|double_click|right_click|type|press|scroll|wait|done|fail","x":0,"y":0,"text":"","keys":"","amount":0,'
          '"note":"what you see and why"}}\n'
          'x,y are pixel positions in this image (for clicks). "press" takes keys like "enter", "ctrl+l", "win". '
          '"scroll" amount: negative = down. Use "done" when the goal is visibly complete and "fail" if it cannot be done. '
          'Never type passwords or payment details; use "fail" if they are needed.')


def parse_step(text):
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        raise ValueError('The model did not give an action.')
    step = json.loads(m.group(0))
    if not isinstance(step, dict) or step.get('action') not in ('click', 'double_click', 'right_click', 'move', 'type', 'press', 'scroll', 'wait', 'done', 'fail'):
        raise ValueError('The model gave an unknown action.')
    return step


def computer_task(goal, llm, check, max_steps=MAX_STEPS, shoot=None, act=None, stop=None):
    """Screenshot -> model picks one action -> do it, until done/fail/stop. Returns a summary dict.
    `check()` raises when the user pressed Stop; shoot/act/stop are injectable for tests."""
    shoot, act, stop = shoot or screen, act or perform, stop or cursor_in_corner
    if os.name != 'nt' and act is perform:
        raise RuntimeError('Mouse and keyboard control only works on the Windows PC.')
    log('task', goal)
    history, steps = [], 0
    for steps in range(1, max_steps + 1):
        check()
        if stop():
            log('stopped', 'mouse in the top-left corner')
            return {'stopped': 'You moved the mouse to the corner, so I stopped.', 'steps': history}
        shot, size = shoot()
        reply = llm(PROMPT.format(goal=goal, w=size[0], h=size[1], history='\n'.join(history[-8:]) or '(none yet)'), images=[shot], max_tokens=220)
        try:
            step = parse_step(reply)
        except (ValueError, json.JSONDecodeError):
            history.append(f'{steps}. (unclear reply, retrying)');continue
        note = ' '.join(str(step.get('note') or '').split())[:120]
        if step['action'] in ('done', 'fail'):
            log(step['action'], note)
            return {('done' if step['action'] == 'done' else 'could_not_finish'): note or step['action'], 'steps': history}
        check()
        if stop():
            return {'stopped': 'You moved the mouse to the corner, so I stopped.', 'steps': history}
        desc = step['action'] + (f" at {step.get('x')},{step.get('y')}" if 'click' in step['action'] or step['action'] == 'move' else '') + \
               (f" '{str(step.get('text'))[:40]}'" if step['action'] == 'type' else '') + (f" {step.get('keys')}" if step['action'] == 'press' else '')
        try:
            act(step, size)
            history.append(f'{steps}. {desc} ({note})')
        except ValueError as e:
            history.append(f'{steps}. {desc} failed: {e}')
        log('step', history[-1])
        time.sleep(.6)   # let the screen update before the next look
    return {'could_not_finish': f'Stopped after {max_steps} steps.', 'steps': history}
