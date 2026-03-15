#!/usr/bin/env python3
import serial, json, time, os, sys, threading, socket

PORT        = "/dev/ttyUSB0"
BAUD        = 9600
CONFIG_FILE = os.path.expanduser("~/fanctl/fanconfig.json")
STATUS_FILE = "/tmp/fanctl_status.json"
SOCKET_PATH = "/tmp/fanctl.sock"

DEFAULT_CONFIG = {
    "exhaust_mins": 180,
    "intake_mins":  120,
    "break_mins":   30,
    "warn_temp":    35.0,
    "danger_temp":  50.0
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(c):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(c, f, indent=2)

serial_lock   = threading.Lock()
state_lock    = threading.Lock()
auto_running  = False
auto_thread   = None
auto_state    = "idle"
time_left     = 0
temp_override = False
cfg           = {}
profile       = "auto"
last_status   = {}

def send_cmd(s, cmd):
    with serial_lock:
        s.write(cmd.encode())
        time.sleep(0.15)

def get_status(s):
    with serial_lock:
        s.write(b's')
        time.sleep(0.3)
        try:
            return json.loads(s.readline().decode().strip())
        except:
            return None

def write_status():
    with state_lock:
        data = {**last_status,
                "profile":    profile,
                "auto_state": auto_state,
                "time_left":  time_left}
    with open(STATUS_FILE, 'w') as f:
        json.dump(data, f)

def status_poller(s):
    global last_status
    while True:
        d = get_status(s)
        if d:
            with state_lock:
                last_status = d
            write_status()
        time.sleep(2)

def auto_loop(s):
    global auto_running, auto_state, time_left, temp_override, cfg

    def run_phase(phase, fan1, fan2, duration_secs):
        global auto_state, time_left, temp_override, cfg
        auto_state = phase
        send_cmd(s, '1' if fan1 else '2')
        send_cmd(s, '3' if fan2 else '4')
        elapsed = 0
        while elapsed < duration_secs and auto_running:
            with state_lock:
                d = last_status
            if d and d.get('danger'):
                auto_state = "danger"
                return False
            if d and d.get('t', 0) >= cfg['warn_temp'] and not temp_override:
                temp_override = True
                send_cmd(s, '5')
                auto_state = "afterburner"
            elif d and d.get('t', 0) < cfg['warn_temp'] and temp_override:
                temp_override = False
                send_cmd(s, '1' if fan1 else '2')
                send_cmd(s, '3' if fan2 else '4')
                auto_state = phase
            time_left = duration_secs - elapsed
            write_status()
            time.sleep(1)
            elapsed += 1
        return True

    while auto_running:
        if not run_phase("exhaust", False, True,  cfg['exhaust_mins'] * 60): break
        if not auto_running: break
        if not run_phase("intake",  True,  False, cfg['intake_mins']  * 60): break
        if not auto_running: break
        if not run_phase("rest",    False, False, cfg['break_mins']   * 60): break

    send_cmd(s, '0')
    auto_state = "idle"
    write_status()

def start_auto(s):
    global auto_running, auto_thread, time_left, cfg
    auto_running = True
    time_left    = cfg['exhaust_mins'] * 60
    auto_thread  = threading.Thread(target=auto_loop, args=(s,), daemon=True)
    auto_thread.start()

def stop_auto(s):
    global auto_running
    auto_running = False
    send_cmd(s, '0')

def handle_command(s, cmd):
    global profile, cfg, auto_running
    if cmd == 'auto':
        if auto_running: stop_auto(s); time.sleep(0.5)
        profile = "auto"
        start_auto(s)
    elif cmd == 'manual':
        stop_auto(s)
        profile = "manual"
    elif cmd in ['1','2','3','4','5','0','l','r']:
        send_cmd(s, cmd)
    elif cmd.startswith('cfg:'):
        try:
            new_cfg = json.loads(cmd[4:])
            cfg.update(new_cfg)
            save_config(cfg)
        except:
            pass
    write_status()

def socket_server(s):
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)
    srv.listen(5)
    while True:
        conn, _ = srv.accept()
        try:
            cmd = conn.recv(256).decode().strip()
            handle_command(s, cmd)
            conn.sendall(b'ok')
        except:
            pass
        finally:
            conn.close()

def main():
    global cfg, profile
    cfg     = load_config()
    profile = "auto"

    try:
        with serial.Serial(PORT, BAUD, timeout=2) as s:
            time.sleep(1.5)
            threading.Thread(target=status_poller, args=(s,), daemon=True).start()
            threading.Thread(target=socket_server, args=(s,), daemon=True).start()
            time.sleep(0.5)
            start_auto(s)
            while True:
                time.sleep(1)
    except serial.SerialException as e:
        print(f"Serial error: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
