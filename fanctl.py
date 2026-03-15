#!/usr/bin/env python3
import json, time, os, sys, curses, socket

STATUS_FILE = "/tmp/fanctl_status.json"
SOCKET_PATH = "/tmp/fanctl.sock"
CONFIG_FILE = os.path.expanduser("~/fanctl/fanconfig.json")

DEFAULT_CONFIG = {
    "exhaust_mins": 180,
    "intake_mins":  120,
    "break_mins":   30,
    "warn_temp":    35.0,
    "danger_temp":  50.0
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE) as f:
        return json.load(f)

def read_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except:
        return None

def send_cmd(cmd):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET_PATH)
        sock.sendall(cmd.encode())
        sock.recv(16)
        sock.close()
    except Exception as e:
        pass

def draw_main(stdscr):
    stdscr.erase()
    d = read_status()

    if not d:
        stdscr.addstr(0, 0, "  Daemon not running. Start with: sudo systemctl start fanctld")
        stdscr.addstr(2, 0, "  q=Quit")
        stdscr.refresh()
        return

    GREEN   = curses.color_pair(1)
    RED     = curses.color_pair(2)
    YELLOW  = curses.color_pair(3)
    PURPLE  = curses.color_pair(4)
    CYAN    = curses.color_pair(5)
    BLUE    = curses.color_pair(6)
    ORANGE  = curses.color_pair(3) | curses.A_BOLD  # yellow+bold ≈ orange in terminals

    f1      = ("ON ", GREEN) if d.get('f1') else ("OFF", RED)
    f2      = ("ON ", GREEN) if d.get('f2') else ("OFF", RED)
    led     = ("ON ", GREEN) if d.get('led', 1) else ("OFF", RED)

    danger  = d.get('danger', 0)
    prof    = d.get('profile', 'auto')
    state   = d.get('auto_state', 'idle')
    tl      = d.get('time_left', 0)
    mins    = int(tl // 60)
    secs    = int(tl % 60)
    row     = 0

    profile_color = PURPLE if prof == "auto" else CYAN
    state_color   = {
        "exhaust":     GREEN,
        "intake":      GREEN,
        "afterburner": ORANGE,
        "rest":        BLUE,
        "idle":        RED,
        "danger":      YELLOW | curses.A_BOLD,
    }.get(state, GREEN)

    def p(line):
        nonlocal row
        try: stdscr.addstr(row, 0, line)
        except curses.error: pass
        row += 1

    def p_colored(prefix, value, color, suffix):
        nonlocal row
        try:
            stdscr.addstr(row, 0, prefix)
            stdscr.addstr(value, color)
            stdscr.addstr(suffix)
        except curses.error: pass
        row += 1

    p("╔══════════════════════════════════╗")
    p("║      Server Fan Controller       ║")
    p("╠══════════════════════════════════╣")
    p(f"║  Temp:      {d.get('t', 0):.1f}C                  ")
    p(f"║  Humidity:  {d.get('h', 0):.1f}%                  ")
    p("╠══════════════════════════════════╣")
    p_colored("║  Intake:    ", f1[0], f1[1], "                       ")
    p_colored("║  Exhaust:   ", f2[0], f2[1], "                       ")
    p_colored("║  LED:       ", led[0], led[1], "                       ")
    p("╠══════════════════════════════════╣")
    p_colored("║  Profile:   ", prof.upper(),  profile_color, "                       ")
    p_colored("║  State:     ", state.upper(), state_color,   "                       ")
    if prof == "auto":
        p(f"║  Next in:   {mins:02d}m {secs:02d}s                 ")
    p("╚══════════════════════════════════╝")

    if danger:
        row += 1
        try: stdscr.addstr(row, 0, "  !! DANGER: Thermal shutdown active!", YELLOW | curses.A_BOLD)
        except curses.error: pass
        row += 2

    row += 1
    p("── Controls ────────────────────────")
    p("  a=Auto  m=Manual  e=Edit Timings")
    p("  l=LED   r=Reset   q=Quit")
    stdscr.refresh()

def edit_screen(stdscr):
    cfg = load_config()
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.timeout(-1)

    fields = [
        ("exhaust_mins", "Exhaust duration (mins)"),
        ("intake_mins",  "Intake duration  (mins)"),
        ("break_mins",   "Break duration   (mins)"),
        ("warn_temp",    "Warn temp        (C)   "),
        ("danger_temp",  "Danger temp      (C)   "),
    ]

    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "── Edit Timings ────────────────────")
        for i, (key, label) in enumerate(fields):
            stdscr.addstr(i + 2, 0, f"  {i+1}. {label}: {cfg[key]}")
        stdscr.addstr(len(fields) + 3, 0, "  Number to edit, b to go back: ")
        stdscr.refresh()

        choice = stdscr.getstr().decode().strip()
        if choice == 'b':
            break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(fields):
                key, label = fields[idx]
                stdscr.addstr(len(fields) + 4, 0, "  New value: ")
                stdscr.refresh()
                val = stdscr.getstr().decode().strip()
                cfg[key] = int(val) if 'mins' in key else float(val)
                send_cmd(f"cfg:{json.dumps(cfg)}")
                stdscr.addstr(len(fields) + 5, 0, "  Saved.")
                stdscr.refresh()
                time.sleep(0.8)
        except (ValueError, IndexError):
            stdscr.addstr(len(fields) + 5, 0, "  Invalid input.")
            stdscr.refresh()
            time.sleep(0.8)

    curses.noecho()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(1000)
    stdscr.clear()
    stdscr.refresh()

def manual_screen(stdscr):
    stdscr.nodelay(True)
    stdscr.timeout(1000)

    while True:
        stdscr.clear()
        d = read_status()
        row = 0
        try:
            stdscr.addstr(row, 0, "── Manual Control ──────────────────"); row += 1
            if d:
                f1 = "ON " if d.get('f1') else "OFF"
                f2 = "ON " if d.get('f2') else "OFF"
                stdscr.addstr(row, 0, f"  Intake: {f1}   Exhaust: {f2}"); row += 1
                stdscr.addstr(row, 0, f"  Temp: {d.get('t',0):.1f}C   Humidity: {d.get('h',0):.1f}%"); row += 1
            row += 1
            stdscr.addstr(row, 0, "  1=Intake ON    2=Intake OFF"); row += 1
            stdscr.addstr(row, 0, "  3=Exhaust ON   4=Exhaust OFF"); row += 1
            stdscr.addstr(row, 0, "  5=Afterburner  0=All OFF"); row += 1
            stdscr.addstr(row, 0, "  l=Toggle LED   b=Back"); row += 1
        except curses.error:
            pass
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('b'):
            break
        elif key in [ord(c) for c in '1234500l']:
            send_cmd(chr(key))

def main_loop(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(1000)
    curses.use_default_colors()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN,   -1)
    curses.init_pair(2, curses.COLOR_RED,     -1)
    curses.init_pair(3, curses.COLOR_YELLOW,  -1)
    curses.init_pair(4, curses.COLOR_MAGENTA, -1)
    curses.init_pair(5, curses.COLOR_CYAN,    -1)
    curses.init_pair(6, curses.COLOR_BLUE,    -1)

    while True:
        draw_main(stdscr)
        key = stdscr.getch()

        if key == ord('q'):
            break
        elif key == ord('a'):
            send_cmd('auto')
        elif key == ord('m'):
            send_cmd('manual')
            manual_screen(stdscr)
        elif key == ord('e'):
            edit_screen(stdscr)
        elif key == ord('l'):
            send_cmd('l')
        elif key == ord('r'):
            send_cmd('r')

def main():
    curses.wrapper(main_loop)

if __name__ == "__main__":
    main()
