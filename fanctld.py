#!/usr/bin/env python3
import serial, json, time, os, sys, threading, socket

PORT        = "/dev/ttyUSB0"
BAUD        = 9600
CONFIG_FILE = os.path.expanduser("~/fanctl/fanconfig.json")
STATUS_FILE = "/tmp/fanctl_status.json"
SOCKET_PATH = "/tmp/fanctl.sock"
STATE_FILE  = os.path.expanduser("~/fanctl/fanctl_state.json")

def find_port():
    import glob
    while True:
        ports = glob.glob('/dev/ttyUSB*')
        if ports:
            return ports[0]
        print("Waiting for device...")
        time.sleep(3)

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

def save_state():
    with open(STATE_FILE, 'w') as f:
        json.dump({"auto_state": auto_state, "time_left": time_left, "profile": profile, "led": led_enabled}, f)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return None

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
led_enabled   = True
current_serial = None

def send_cmd(s, cmd):
    target = s if s else current_serial
    if not target:
        return
    with serial_lock:
        try:
            target.write(cmd.encode())
            time.sleep(0.15)
        except serial.SerialException:
            time.sleep(2)
            target.write(cmd.encode())
            time.sleep(0.15)

def get_status(s):
    with serial_lock:
        try:
            s.write(b's')
            time.sleep(0.3)
            return json.loads(s.readline().decode().strip())
        except serial.SerialException:
            raise
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

serial_alive = True

def status_poller(s):
    global last_status, serial_alive
    while serial_alive:
        try:
            d = get_status(s)
            if d:
                with state_lock:
                    last_status = d
                write_status()
        except Exception:
            serial_alive = False
            return
        time.sleep(2)

def auto_loop(s):
    global auto_running, auto_state, time_left, temp_override, cfg

    phases = [
        ("exhaust", False, True,  lambda: cfg['exhaust_mins'] * 60),
        ("intake",  True,  False, lambda: cfg['intake_mins']  * 60),
        ("rest",    False, False, lambda: cfg['break_mins']   * 60),
    ]
    phase_names = [p[0] for p in phases]

    saved = load_state()
    start_phase    = 0
    resume_elapsed = 0
    if saved and saved.get('auto_state') in phase_names:
        start_phase    = phase_names.index(saved['auto_state'])
        resume_elapsed = max(0, phases[start_phase][3]() - saved.get('time_left', 0))

    def run_phase(phase, fan1, fan2, duration_secs, resume=0):
        global auto_state, time_left, temp_override, cfg
        auto_state = phase
        send_cmd(s, '1' if fan1 else '2')
        send_cmd(s, '3' if fan2 else '4')
        elapsed = resume
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
            save_state()
            time.sleep(1)
            elapsed += 1
        return True

    while auto_running:
        for i, (phase, fan1, fan2, dur_fn) in enumerate(phases):
            resume = resume_elapsed if i == start_phase else 0
            if not run_phase(phase, fan1, fan2, dur_fn(), resume=resume):
                return
            if not auto_running:
                return
        start_phase    = 0
        resume_elapsed = 0

    send_cmd(s, '0')
    auto_state = "idle"
    write_status()

def start_auto(s):
    global auto_running, auto_thread, time_left, cfg
    auto_running = True
    time_left    = cfg['exhaust_mins'] * 60

    # reapply fan state immediately based on saved state
    saved = load_state()
    if saved:
        phase = saved.get('auto_state', 'exhaust')
        if phase == 'exhaust':
            send_cmd(s, '2'); send_cmd(s, '3')
        elif phase == 'intake':
            send_cmd(s, '1'); send_cmd(s, '4')
        elif phase == 'rest':
            send_cmd(s, '0')

    auto_thread = threading.Thread(target=auto_loop, args=(s,), daemon=True)
    auto_thread.start()

def stop_auto(s):
    global auto_running
    auto_running = False
    if s:
        send_cmd(s, '0')

def handle_command(s, cmd):
    global profile, cfg, auto_running, led_enabled
    s = current_serial
    if not s:
        return
    if cmd == 'auto':
        if auto_running: stop_auto(s); time.sleep(0.5)
        profile = "auto"
        start_auto(s)
    elif cmd == 'manual':
        stop_auto(s)
        profile = "manual"
    elif cmd == 'l':
        led_enabled = not led_enabled
        send_cmd(s, 'l')
        save_state()
    elif cmd in ['1','2','3','4','5','0','r']:
        send_cmd(s, cmd)
    elif cmd.startswith('cfg:'):
        try:
            new_cfg = json.loads(cmd[4:])
            cfg.update(new_cfg)
            save_config(cfg)
        except:
            pass
    write_status()

def socket_server():
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
            handle_command(None, cmd)
            conn.sendall(b'ok')
        except:
            pass
        finally:
            conn.close()

def main():
    global cfg, profile
    cfg     = load_config()
    profile = "auto"

    socket_started = False

    while True:
        port = find_port()
        print(f"Connecting to {port}...")
        try:
            with serial.Serial(port, BAUD, timeout=2) as s:
                global serial_alive, current_serial
                serial_alive   = True
                current_serial = s
                time.sleep(3)
                for _ in range(10):
                    d = get_status(s)
                    if d:
                        break
                    time.sleep(1)
                # restore led state
                if not led_enabled:
                    send_cmd(s, 'l')
                threading.Thread(target=status_poller, args=(s,), daemon=True).start()
                if not socket_started:
                    threading.Thread(target=socket_server, daemon=True).start()
                    socket_started = True
                time.sleep(0.5)
                start_auto(s)
                while serial_alive:
                    time.sleep(1)
                print("Serial disconnected, reconnecting...")
                current_serial = None
                stop_auto(None)
                time.sleep(3)
        except serial.SerialException as e:
            print(f"Serial error: {e}, reconnecting in 5s...")
            current_serial = None
            stop_auto(None)
            time.sleep(5)

if __name__ == "__main__":
    main()
