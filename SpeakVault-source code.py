# -*- coding: utf-8 -*-
import os
import threading
import subprocess
import sys
import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import csv
from datetime import datetime
from gtts import gTTS
import pyttsx3
from pydub import AudioSegment, effects, silence
import re
import time

try:
    from elevenlabs.client import ElevenLabs
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False



CHAR_LIMIT = 950
LANG = "pl"
SUPPORTED_FORMATS = ["ogg", "mp3", "wav"]
DEFAULT_FORMAT = "ogg"
CPU_THREADS = os.cpu_count() or 8
DEFAULT_SETTINGS_FILE = "speakvault_settings.json"

stop_event = threading.Event()
event_log = []

def log_event(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_log.append(f"[{now}] {msg}")

def split_text(text, limit):
    words = text.split()
    result, temp = [], ""
    for w in words:
        if len(temp + w) + 1 > limit:
            result.append(temp.strip())
            temp = w + " "
        else:
            temp += w + " "
    if temp: result.append(temp.strip())
    return result

def get_sequential_filename(folder, prefix, ext, start=1):
    idx = start
    while True:
        filename = os.path.join(folder, f"{prefix} ({idx}).{ext}")
        if not os.path.exists(filename):
            return filename, idx
        idx += 1

def read_text_file_autoencoding(path):
    encodings = ['utf-8', 'cp1250', 'windows-1250', 'latin2', 'iso8859_2']
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    with open(path, 'rb') as f:
        content = f.read()
    try:
        return content.decode('utf-8')
    except Exception:
        return content.decode('cp1250', errors='replace')

def parse_lines_txt(fn):
    lines = read_text_file_autoencoding(fn).splitlines()
    return [(str(i+1), line.strip()) for i, line in enumerate(lines) if line.strip()]

def parse_lines_csv(fn):
    encodings = ['utf-8', 'cp1250', 'windows-1250', 'latin2', 'iso8859_2']
    for enc in encodings:
        try:
            with open(fn, "r", encoding=enc) as f:
                reader = csv.reader(f)
                return [(str(i+1), row[0]) for i, row in enumerate(reader) if row]
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    with open(fn, "rb") as f:
        content = f.read()
    try:
        txt = content.decode('utf-8')
    except Exception:
        txt = content.decode('cp1250', errors='replace')
    reader = csv.reader(txt.splitlines())
    return [(str(i+1), row[0]) for i, row in enumerate(reader) if row]

def parse_lines_srt(fn):
    content = read_text_file_autoencoding(fn)
    pattern = re.compile(r'(\d+)\s*\n\s*([\d:,]+ --> [\d:,]+)\s*\n(.*?)(?=\n\s*\n|\Z)', re.DOTALL)
    entries = []
    for match in pattern.finditer(content):
        num = match.group(1).strip()
        time = match.group(2).strip()
        text = match.group(3).replace('\n', ' ').strip()
        start_str, end_str = time.split(" --> ")
        def srt_time_to_ms(t):
            h, m, s_ms = t.split(":")
            s, ms = s_ms.split(",")
            return (int(h)*3600 + int(m)*60 + int(s))*1000 + int(ms)
        start_ms = srt_time_to_ms(start_str)
        end_ms = srt_time_to_ms(end_str)
        entries.append((num, time, text, start_ms, end_ms))
    return entries

def parse_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return parse_lines_csv(path)
    elif ext == ".srt":
        return parse_lines_srt(path)
    else:
        return parse_lines_txt(path)

def play_audio_file(filename):
    if not os.path.exists(filename):
        messagebox.showerror("Błąd", f"Plik nie istnieje:\n{filename}")
        return
    try:
        if sys.platform == "win32":
            os.startfile(filename)
        elif sys.platform == "darwin":
            subprocess.call(["afplay", filename])
        else:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            subprocess.call(
                ["ffplay", "-nodisp", "-autoexit", filename],
                creationflags=flags
            )
    except Exception as e:
        messagebox.showerror("Błąd odtwarzania", str(e))

from gtts.tts import gTTSError

def safe_gtts(text, lang, filename, retries=5):
    for attempt in range(1, retries+1):
        try:
            gTTS(text=text, lang=lang).save(filename)
            time.sleep(1)  # 1 sekunda po Google TTS!
            if not os.path.exists(filename) or os.path.getsize(filename) < 1024:
                raise gTTSError("Plik TTS jest pusty lub zbyt mały (API mogło zwrócić pustą odpowiedź).")
            return True
        except Exception as e:
            print(f"Błąd gTTS: {e} (próba {attempt}/{retries})")
            if attempt == retries:
                return False
    return False

def generate_audio_task(task, log, set_last_audio=None):
    import traceback
    stop_event.clear()
    path = task['file']
    start = int(task['start_line'])
    end = int(task['end_line'])
    engine = task['engine']
    fmt = task['format']
    out_dir = task['output_dir']
    merge = task['merge']
    srt_1s_ciszy = task.get("srt_1s_ciszy", False)
    tts_voice_id = task.get('voice_id', "")
    eleven_api_key = task.get('eleven_api_key', "")
    eleven_voice_id = task.get('eleven_voice_id', "")
    tempo = float(task.get("tempo", 1.0))
    pitch = float(task.get("pitch", 1.0))
    gain = float(task.get("gain", 1.0))
    global_stretch = task.get('global_stretch', False)

    if not out_dir or not os.path.isdir(out_dir):
        log("‼️ Wybierz folder wyjściowy audio przed startem!")
        messagebox.showerror("Błąd", "Musisz wybrać istniejący folder wyjściowy audio przed startem!")
        return

    os.makedirs(out_dir, exist_ok=True)
    lines = parse_file(path)
    total_lines = len(lines)
    last_file = None

    def process_tts_fragment(chunk, tmp):
        if engine == "Google TTS":
            ok = safe_gtts(chunk, LANG, tmp, retries=5)
            return ok
        elif engine == "Windows TTS":
            tts_engine = pyttsx3.init()
            if tts_voice_id:
                tts_engine.setProperty('voice', tts_voice_id)
            tts_engine.save_to_file(chunk, tmp)
            tts_engine.runAndWait()
            del tts_engine
            return True
        elif engine == "ElevenLabs":
            if not ELEVENLABS_AVAILABLE:
                log("Moduł elevenlabs nie zainstalowany! pip install elevenlabs")
                return False
            client = ElevenLabs(api_key=eleven_api_key)
            result = client.text_to_speech.convert(
                voice_id=eleven_voice_id, model_id="eleven_turbo_v2_5", text=chunk,
                output_format="opus_48000_64" if fmt == "ogg" else fmt
            )
            with open(tmp, "wb") as f:
                for part in result:
                    f.write(part)
            return True
        return False

    # Obsługa TXT/CSV/SRT nie-merge i merge
    lines = lines[start-1:end] if end > 0 else lines[start-1:]
    full_audio = AudioSegment.silent(duration=0)
    idx = 1
    last_file = None
    output_files = []

    for i, entry in enumerate(lines):
        if path.lower().endswith('.srt'):
            label, _, text, start_ms, end_ms = entry
        else:
            label, text = entry
        for part_i, chunk in enumerate(split_text(text, CHAR_LIMIT)):
            # Check for stop before processing each chunk
            if stop_event.is_set():
                log("🛑 Zadanie zatrzymane przez użytkownika – zapisywanie dotychczasowego audio...")
                if merge and len(full_audio) > 0:
                    try:
                        output_filename, _ = get_sequential_filename(out_dir, "output1", fmt)
                        full_audio.export(output_filename, format=fmt)
                        log(f"Zapisano częściowe scalone: {os.path.basename(output_filename)}")
                        log_event(f"Częściowe zadanie TTS zakończone: {os.path.basename(output_filename)}")
                        last_file = output_filename
                        if set_last_audio:
                            set_last_audio(output_filename)
                    except Exception as e:
                        log(f"Błąd przy zapisie częściowego scalonego: {e}")
                        log_event(f"Błąd przy zapisie częściowego scalonego: {e}")
                log("Przerywam dalsze przetwarzanie.")
                return
            percent = int((i+1) / total_lines * 100)
            log(f"[{percent}%] {label}.{part_i+1}: {chunk[:40]}")
            tmp = os.path.join(out_dir, f"_tmp_{label}_{part_i}.{fmt}")
            try:
                ok = process_tts_fragment(chunk, tmp)
                if not ok:
                    log(f"Błąd TTS: nie udało się wygenerować fragmentu: {chunk[:40]}")
                    continue
                segment = AudioSegment.from_file(tmp)
                if tempo != 1.0:
                    segment = segment.speedup(playback_speed=tempo)
                if pitch != 1.0:
                    segment = segment._spawn(segment.raw_data, overrides={
                        "frame_rate": int(segment.frame_rate * pitch)
                    }).set_frame_rate(segment.frame_rate)
                if gain != 1.0:
                    segment += (20 * (gain-1))
                if merge:
                    full_audio += segment
                else:
                    output_filename, idx = get_sequential_filename(out_dir, "output1", fmt, idx)
                    segment.export(output_filename, format=fmt)
                    log(f"Zapisano: {os.path.basename(output_filename)}")
                    last_file = output_filename
                    output_files.append(output_filename)
                    idx += 1
                os.remove(tmp)
            except Exception as e:
                log(f"Błąd: {e}")
                import traceback; log(traceback.format_exc())
                continue

    if merge and len(full_audio) > 0:
        try:
            output_filename, _ = get_sequential_filename(out_dir, "output1", fmt)
            full_audio.export(output_filename, format=fmt)
            log(f"Zapisano scalone: {os.path.basename(output_filename)}")
            log_event(f"Zadanie TTS zakończone: {os.path.basename(output_filename)}")
            last_file = output_filename
        except Exception as e:
            log(f"Błąd przy scalaniu: {e}")
            log_event(f"Błąd przy scalaniu: {e}")

    if set_last_audio and last_file:
        set_last_audio(last_file)

def batch_audio_task(files, outdir, speed, pitch, gain, silence_remove, fmt, start_s, end_s, log):
    for i, path in enumerate(files):
        try:
            log(f"[{i+1}/{len(files)}] Otwieram: {os.path.basename(path)}")
            audio = AudioSegment.from_file(path)
            orig_len = len(audio)
            if start_s > 0 or end_s > 0:
                start_ms = int(start_s*1000)
                end_ms = int(end_s*1000) if end_s > 0 else orig_len
                audio = audio[start_ms:end_ms]
                log(f"Przycięto: {start_ms}ms - {end_ms}ms")
            if silence_remove:
                audio = effects.normalize(audio)
                chunks = silence.split_on_silence(audio, min_silence_len=400, silence_thresh=audio.dBFS-24, keep_silence=50)
                if chunks:
                    audio = sum(chunks)
                    log(f"Usunięto ciszę ({len(chunks)} fragmentów)")
            if speed != 1.0:
                audio = audio.speedup(playback_speed=speed)
            if pitch != 1.0:
                audio = audio._spawn(audio.raw_data, overrides={
                    "frame_rate": int(audio.frame_rate * pitch)
                }).set_frame_rate(audio.frame_rate)
            if gain != 1.0:
                audio += (20 * (gain-1))
            output_filename, _ = get_sequential_filename(outdir, "output2", fmt)
            audio.export(output_filename, format=fmt)
            log(f"✔️ Zapisano: {output_filename}")
        except Exception as e:
            log(f"❌ Błąd: {e}")

def ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def save_settings(settings, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        log_event(f"Ustawienia zapisane do: {path}")
        return True
    except Exception as e:
        log_event(f"Błąd zapisu ustawień: {e}")
        return False

def load_settings(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

class SpeakVaultApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SpeakVault")
        self.root.geometry("1200x800")
        self.root.configure(bg="#181e22")
        self.apply_dark_theme(root)

        try:
            if os.path.exists("logo.ico"):
                self.root.iconbitmap("logo.ico")
        except Exception:
            pass

        self.settings_path_var = tk.StringVar(value=DEFAULT_SETTINGS_FILE)
        self.settings_name_var = tk.StringVar(value="speakvault_settings.json")
        self.settings = load_settings(self.settings_path_var.get())

        self.notebook = ttk.Notebook(root, style="Custom.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self.tts_frame = ttk.Frame(self.notebook)
        self.build_tts_tab(self.tts_frame)
        self.notebook.add(self.tts_frame, text="Generator mowy (TTS)")

        self.batch_frame = ttk.Frame(self.notebook)
        self.build_batch_tab(self.batch_frame)
        self.notebook.add(self.batch_frame, text="Narzędzia batch audio")

        self.events_frame = ttk.Frame(self.notebook)
        self.build_events_tab(self.events_frame)
        self.notebook.add(self.events_frame, text="Dziennik zdarzeń")

        self.last_audio_path = None
        self.batch_files = []

        self.load_settings_to_gui()

    def apply_dark_theme(self, root):
        style = ttk.Style(root)
        style.theme_use("clam")
        main_bg = "#181e22"
        entry_bg = "#252c34"
        accent = "#62ffb3"
        tab_bg = "#232d33"
        tab_fg = "#e6e6e6"
        tab_sel_bg = "#62ffb3"
        tab_sel_fg = "#232d33"
        style.configure(".", background=main_bg, foreground="#e6e6e6")
        style.configure("TFrame", background=main_bg)
        style.configure("TLabel", background=main_bg, foreground=accent, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background="#1e2328", foreground="#e6e6e6", borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.configure("TCheckbutton", background=main_bg, foreground="#e6e6e6")
        style.configure("TEntry", fieldbackground=entry_bg, background=entry_bg, foreground="#e6e6e6")
        style.configure("TCombobox", fieldbackground=entry_bg, background=entry_bg, foreground="#e6e6e6", arrowcolor=accent, selectbackground=entry_bg, selectforeground="#e6e6e6")
        style.map("TCombobox", fieldbackground=[("readonly", entry_bg)], background=[("readonly", entry_bg)], foreground=[("readonly", "#e6e6e6")])
        style.map("TButton", background=[("active", "#232e38")])
        style.configure("Custom.TLabelframe", background=main_bg, bordercolor="#62ffb3", borderwidth=2)
        style.configure("Custom.TLabelframe.Label", background=main_bg, foreground=accent, font=("Segoe UI", 11, "bold"))
        style.layout("Custom.TNotebook.Tab", [
            ('Notebook.tab', {'sticky': 'nswe', 'children': [
                ('Notebook.padding', {'side': 'top', 'sticky': 'nswe', 'children': [
                    ('Notebook.label', {'side': 'top', 'sticky': ''})
                ]})
            ]}),
        ])
        style.configure("Custom.TNotebook.Tab",
                        background=tab_bg,
                        foreground=tab_fg,
                        font=("Segoe UI", 11, "bold"),
                        padding=[12, 6],
                        borderwidth=1)
        style.map("Custom.TNotebook.Tab",
                  background=[("selected", tab_sel_bg)],
                  foreground=[("selected", tab_sel_fg)])
        style.configure("Custom.TNotebook", background=main_bg, tabposition='n')

    def add_credit(self, parent):
        credit = tk.Label(parent, text="by fifizkonopii & Ekrixc & Ai v1.0", fg="#00ff75", bg="#181e22", font=("Segoe UI", 12, "italic"))
        credit.place(relx=1.0, rely=1.0, x=-18, y=-10, anchor="se")

    def build_tts_tab(self, frame):
        left = ttk.Frame(frame)
        left.pack(side="left", fill="y", padx=(0,20), expand=False)
        right = ttk.Frame(frame)
        right.pack(side="right", fill="both", expand=True)

        log_label = tk.Label(right, text="Log generowania mowy", fg="#00ff75", bg="#181e22", font=("Segoe UI", 13, "bold"))
        log_label.pack(anchor="nw", padx=18, pady=(10,0))
        tts_log_frame = tk.Frame(right, bg="#181e22", highlightbackground="#00ff75", highlightthickness=2)
        tts_log_frame.pack(fill="both", expand=True, padx=8, pady=(4,8))
        self.tts_log_right = tk.Text(tts_log_frame, height=30, bg="#181e22", fg="#62ffb3", font=("Consolas", 11), relief="flat", insertbackground="#62ffb3")
        self.tts_log_right.pack(fill="both", expand=True, padx=8, pady=8)
        log_credit = tk.Label(right, text="by fifizkonopii & Ekrixc & Ai v1.0", fg="#00ff75", bg="#181e22", font=("Segoe UI", 11, "italic"))
        log_credit.pack(anchor="se", padx=8, pady=(0,8))

        self.add_credit(frame)

        ttk.Label(left, text="Plik wejściowy TXT/CSV/SRT:").pack(anchor="w")
        self.file_var = tk.StringVar()
        file_row = ttk.Frame(left); file_row.pack(fill="x")
        ttk.Entry(file_row, textvariable=self.file_var, width=38).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Wybierz...", command=self.choose_file).pack(side="left")

        ttk.Label(left, text="Folder wyjściowy audio:").pack(anchor="w", pady=(10,0))
        self.out_var = tk.StringVar(value="audio_output")
        out_row = ttk.Frame(left); out_row.pack(fill="x")
        ttk.Entry(out_row, textvariable=self.out_var, width=38).pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="Wybierz...", command=self.choose_out).pack(side="left")

        ttk.Label(left, text="Start od linii:").pack(anchor="w", pady=(10,0))
        self.start_line = tk.IntVar(value=1)
        ttk.Entry(left, textvariable=self.start_line).pack(fill="x")

        ttk.Label(left, text="Koniec na linii (0 = do końca):").pack(anchor="w")
        self.end_line = tk.IntVar(value=0)
        ttk.Entry(left, textvariable=self.end_line).pack(fill="x")

        ttk.Label(left, text="Silnik mowy:").pack(anchor="w", pady=(10,0))
        self.engine_var = tk.StringVar(value="Google TTS")
        engines = ["Google TTS", "Windows TTS"]
        if ELEVENLABS_AVAILABLE:
            engines.append("ElevenLabs")
        self.engine_box = ttk.Combobox(left, textvariable=self.engine_var, values=engines, state="readonly")
        self.engine_box.pack(fill="x")

        ttk.Label(left, text="Format audio:").pack(anchor="w", pady=(10,0))
        self.fmt_var = tk.StringVar(value=DEFAULT_FORMAT)
        fmt_box = ttk.Combobox(left, textvariable=self.fmt_var, values=SUPPORTED_FORMATS, state="readonly")
        fmt_box.pack(fill="x")

        set_row = ttk.Frame(left)
        set_row.pack(anchor="w", fill="x", pady=(4,0))
        ttk.Label(set_row, text="Plik ustawień:").pack(side="left")
        ttk.Entry(set_row, textvariable=self.settings_path_var, width=28).pack(side="left", fill="x", expand=True)
        ttk.Button(set_row, text="Wybierz...", command=self.choose_settings_dir).pack(side="left")
        ttk.Label(set_row, text="Nazwa pliku:").pack(side="left", padx=(10,0))
        ttk.Entry(set_row, textvariable=self.settings_name_var, width=18).pack(side="left")
        ttk.Button(set_row, text="Odczytaj ustawienia", command=self.read_settings_file).pack(side="left", padx=(10,0))

        self.param_frame = ttk.Frame(left)
        self.param_frame.pack(fill="x", pady=(10,0))
        ttk.Label(self.param_frame, text="Ustawienia silnika mowy:").pack(anchor="w")
        self.merge_var = tk.BooleanVar(value=False)
        self.merge_cb = ttk.Checkbutton(self.param_frame, text="Scal do jednego pliku audio", variable=self.merge_var, command=self.sync_merge_and_1s)
        self.merge_cb.pack(anchor="w", pady=(2,0))
        ttk.Label(self.param_frame, text="Tempo (np. 1.0=normalnie, 1.5=szybciej):").pack(anchor="w", pady=(2,0))
        self.tts_tempo_var = tk.DoubleVar(value=1.0)
        ttk.Entry(self.param_frame, textvariable=self.tts_tempo_var).pack(fill="x")
        ttk.Label(self.param_frame, text="Ton (np. 1.0=normalnie, 1.2=wyżej):").pack(anchor="w", pady=(2,0))
        self.tts_pitch_var = tk.DoubleVar(value=1.0)
        ttk.Entry(self.param_frame, textvariable=self.tts_pitch_var).pack(fill="x")
        ttk.Label(self.param_frame, text="Głośność (np. 1.0=normalnie, 1.5=głośniej):").pack(anchor="w", pady=(2,0))
        self.tts_gain_var = tk.DoubleVar(value=1.0)
        ttk.Entry(self.param_frame, textvariable=self.tts_gain_var).pack(fill="x")

        self.srt_1s_ciszy = tk.BooleanVar(value=False)
        self.srt_1s_ciszy_checkbox = ttk.Checkbutton(self.param_frame, text="Dodaj 1s ciszy po każdym napisie SRT (nie merge)", variable=self.srt_1s_ciszy, command=self.sync_merge_and_1s)
        self.srt_1s_ciszy_checkbox.pack(anchor="w", pady=(2,0))

        self.global_stretch_var = tk.BooleanVar(value=False)
        self.global_stretch_cb = ttk.Checkbutton(self.param_frame, text="Dopasuj audio do czasu SRT/filmu (globalne tempo)", variable=self.global_stretch_var)
        self.global_stretch_cb.pack(anchor="w", pady=(2,0))

        self.engine_option_frame = ttk.Frame(left)
        self.engine_option_frame.pack(fill="x", pady=(10,0))
        self.voice_label = ttk.Label(self.engine_option_frame, text="Wybierz głos Windows TTS")
        self.voice_box = ttk.Combobox(self.engine_option_frame, state="readonly")
        self.eleven_api_label = ttk.Label(self.engine_option_frame, text="ElevenLabs API key:")
        self.eleven_api_var = tk.StringVar()
        self.eleven_api_entry = ttk.Entry(self.engine_option_frame, textvariable=self.eleven_api_var)
        self.eleven_voice_label = ttk.Label(self.engine_option_frame, text="ElevenLabs Voice ID:")
        self.eleven_voice_var = tk.StringVar()
        self.eleven_voice_entry = ttk.Entry(self.engine_option_frame, textvariable=self.eleven_voice_var)

        ttk.Button(left, text="Zapisz ustawienia", command=self.save_settings_from_gui).pack(anchor="w", pady=(12,0))
        btnrow = ttk.Frame(left); btnrow.pack(pady=7, fill="x")
        self.start_btn = ttk.Button(btnrow, text="Start generowania mowy", command=self.start_tts_task)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=2)
        self.stop_btn = ttk.Button(btnrow, text="Zatrzymaj", command=self.stop_tts_task)
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=2)
        self.reset_btn = ttk.Button(btnrow, text="Resetuj", command=self.reset_app)
        self.reset_btn.pack(side="left", fill="x", expand=True, padx=2)
        self.play_btn = ttk.Button(btnrow, text="Odtwórz ostatni plik", command=self.play_last_audio)
        self.play_btn.pack(side="left", fill="x", expand=True, padx=2)

        self.tts_log = self.tts_log_right
        self.voice_id_map = {}
        self.engine_var.trace_add("write", self.on_engine_change)
        self.voice_box.bind("<<ComboboxSelected>>", self.on_voice_select)
        self.selected_voice_id = ""
        self.on_engine_change()

    def sync_merge_and_1s(self, *args):
        if self.merge_var.get():
            self.srt_1s_ciszy.set(False)
            self.srt_1s_ciszy_checkbox.state(['disabled'])
        else:
            self.srt_1s_ciszy_checkbox.state(['!disabled'])

    def choose_settings_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            full_path = os.path.join(folder, self.settings_name_var.get())
            self.settings_path_var.set(full_path)

    def read_settings_file(self):
        fn = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("Wszystkie pliki", "*.*")])
        if fn:
            self.settings_path_var.set(fn)
            self.settings_name_var.set(os.path.basename(fn))
            self.settings = load_settings(fn)
            self.load_settings_to_gui()
            messagebox.showinfo("Ustawienia", f"Odczytano ustawienia z:\n{fn}")

    def play_last_audio(self):
        if self.last_audio_path:
            play_audio_file(self.last_audio_path)
        else:
            messagebox.showinfo("Odtwarzanie", "Brak pliku do odtworzenia.")

    def stop_tts_task(self):
        stop_event.set()
        self.tts_log_write("🛑 Zadanie oznaczone do zatrzymania.")

    def build_batch_tab(self, frame):
        self.add_credit(frame)
        self.batch_outdir = tk.StringVar(value=os.getcwd())
        self.batch_log = None

        file_row = ttk.Frame(frame)
        file_row.pack(fill="x")
        ttk.Button(file_row, text="Dodaj pliki audio", command=self.add_batch_files).pack(side="left")
        ttk.Button(file_row, text="Dodaj folder audio", command=self.add_batch_folder).pack(side="left", padx=5)
        ttk.Label(file_row, text="Wybrane pliki:").pack(side="left", padx=10)
        self.batch_files_box = tk.Listbox(frame, height=6, selectmode="extended", bg="#181e22", fg="#62ffb3", font=("Consolas", 11))
        self.batch_files_box.pack(fill="x", pady=2)

        out_row = ttk.Frame(frame)
        out_row.pack(fill="x", pady=3)
        ttk.Label(out_row, text="Folder wyjściowy audio:").pack(side="left")
        ttk.Entry(out_row, textvariable=self.batch_outdir, width=40).pack(side="left")
        ttk.Button(out_row, text="Wybierz...", command=self.pick_batch_outdir).pack(side="left")

        opt_frm = ttk.Labelframe(frame, text="Opcje przetwarzania audio", style="Custom.TLabelframe")
        opt_frm.pack(fill="x", pady=8)

        ttk.Label(opt_frm, text="Przyspieszenie (np 1.0, 1.2, 2.0):").grid(row=0, column=0, sticky="w")
        self.batch_speed_var = tk.DoubleVar(value=1.0)
        ttk.Entry(opt_frm, textvariable=self.batch_speed_var, width=7).grid(row=0, column=1, sticky="w")

        ttk.Label(opt_frm, text="Ton (np. 1.0=normalny, 1.2=wyżej):").grid(row=1, column=0, sticky="w")
        self.batch_pitch_var = tk.DoubleVar(value=1.0)
        ttk.Entry(opt_frm, textvariable=self.batch_pitch_var, width=7).grid(row=1, column=1, sticky="w")

        ttk.Label(opt_frm, text="Głośność (1=normalnie, 0.8=ciszej, 1.5=głośniej):").grid(row=2, column=0, sticky="w")
        self.batch_gain_var = tk.DoubleVar(value=1.0)
        ttk.Entry(opt_frm, textvariable=self.batch_gain_var, width=7).grid(row=2, column=1, sticky="w")

        self.batch_silence_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frm, text="Usuń ciszę z pliku", variable=self.batch_silence_var).grid(row=3, column=0, sticky="w")

        ttk.Label(opt_frm, text="Konwersja do formatu:").grid(row=4, column=0, sticky="w")
        self.batch_format_var = tk.StringVar(value=DEFAULT_FORMAT)
        ttk.Combobox(opt_frm, textvariable=self.batch_format_var, values=SUPPORTED_FORMATS, width=8, state="readonly").grid(row=4, column=1, sticky="w")

        ttk.Label(opt_frm, text="Start (sekunda):").grid(row=5, column=0, sticky="w")
        self.batch_start_var = tk.DoubleVar(value=0)
        ttk.Entry(opt_frm, textvariable=self.batch_start_var, width=7).grid(row=5, column=1, sticky="w")

        ttk.Label(opt_frm, text="Koniec (sekunda, 0=do końca):").grid(row=6, column=0, sticky="w")
        self.batch_end_var = tk.DoubleVar(value=0)
        ttk.Entry(opt_frm, textvariable=self.batch_end_var, width=7).grid(row=6, column=1, sticky="w")

        batch_btnrow = ttk.Frame(frame); batch_btnrow.pack(pady=7, fill="x")
        ttk.Button(batch_btnrow, text="Start batch audio", command=self.start_batch).pack(side="left", padx=2)
        ttk.Button(batch_btnrow, text="Resetuj", command=self.reset_app).pack(side="left", padx=2)
        ttk.Button(batch_btnrow, text="Odtwórz wybrany plik", command=self.play_selected_batch_audio).pack(side="left", padx=2)

        log_frame = ttk.Labelframe(frame, text="Log batch audio", style="Custom.TLabelframe")
        log_frame.pack(fill="both", expand=True, padx=0, pady=10)
        self.batch_log = tk.Text(log_frame, height=13, bg="#181e22", fg="#62ffb3", font=("Consolas", 11), relief="flat", insertbackground="#62ffb3")
        self.batch_log.pack(fill="both", expand=True, padx=4, pady=4)

    def add_batch_files(self):
        files = filedialog.askopenfilenames(filetypes=[("Audio files", "*.ogg *.mp3 *.wav"), ("All files", "*.*")])
        for f in files:
            if f not in self.batch_files:
                self.batch_files.append(f)
                self.batch_files_box.insert("end", f)

    def add_batch_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            for f in os.listdir(folder):
                if f.lower().endswith((".ogg", ".mp3", ".wav")):
                    full = os.path.join(folder, f)
                    if full not in self.batch_files:
                        self.batch_files.append(full)
                        self.batch_files_box.insert("end", full)

    def pick_batch_outdir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.batch_outdir.set(folder)

    def play_selected_batch_audio(self):
        selected = self.batch_files_box.curselection()
        if not selected:
            messagebox.showinfo("Odtwarzanie", "Wybierz plik z listy.")
            return
        filename = self.batch_files_box.get(selected[0])
        play_audio_file(filename)

    def on_engine_change(self, *_):
        for widget in self.engine_option_frame.winfo_children():
            widget.pack_forget()
        engine = self.engine_var.get()
        if engine == "Windows TTS":
            t = pyttsx3.init()
            voices = t.getProperty('voices')
            voice_names = [v.name for v in voices]
            self.voice_id_map = {v.name: v.id for v in voices}
            self.voice_box['values'] = voice_names
            if voice_names:
                self.voice_box.set(voice_names[0])
                self.selected_voice_id = self.voice_id_map[voice_names[0]]
            else:
                self.voice_box.set("")
                self.selected_voice_id = ""
            self.voice_label.pack(anchor="w")
            self.voice_box.pack(fill="x")
        elif engine == "ElevenLabs":
            self.eleven_api_label.pack(anchor="w")
            self.eleven_api_entry.pack(fill="x")
            self.eleven_voice_label.pack(anchor="w", pady=(6,0))
            self.eleven_voice_entry.pack(fill="x")
        else:
            self.selected_voice_id = ""

    def on_voice_select(self, event):
        name = self.voice_box.get()
        self.selected_voice_id = self.voice_id_map.get(name, "")

    def choose_file(self):
        fn = filedialog.askopenfilename(filetypes=[("Text files", "*.txt *.csv *.srt"),("All files","*.*")])
        if fn: self.file_var.set(fn)

    def choose_out(self):
        folder = filedialog.askdirectory()
        if folder: self.out_var.set(folder)

    def start_tts_task(self):
        stop_event.clear()
        if not self.out_var.get() or not os.path.isdir(self.out_var.get()):
            messagebox.showerror("Błąd", "Musisz wybrać istniejący folder wyjściowy audio!")
            return
        task = {
            "file": self.file_var.get(),
            "output_dir": self.out_var.get(),
            "start_line": self.start_line.get(),
            "end_line": self.end_line.get(),
            "engine": self.engine_var.get(),
            "format": self.fmt_var.get(),
            "merge": self.merge_var.get(),
            "voice_id": self.selected_voice_id if self.engine_var.get() == "Windows TTS" else "",
            "eleven_api_key": self.eleven_api_var.get() if self.engine_var.get() == "ElevenLabs" else "",
            "eleven_voice_id": self.eleven_voice_var.get() if self.engine_var.get() == "ElevenLabs" else "",
            "tempo": self.tts_tempo_var.get(),
            "pitch": self.tts_pitch_var.get(),
            "gain": self.tts_gain_var.get(),
            "srt_1s_ciszy": self.srt_1s_ciszy.get(),
            "global_stretch": self.global_stretch_var.get(),
        }
        self.tts_log.delete("1.0", "end")
        self.tts_log.insert("end", f"--- Start zadania: {task['file']}, silnik: {task['engine']} ---\n")
        threading.Thread(target=generate_audio_task, args=(task, self.tts_log_write, self.set_last_audio), daemon=True).start()

    def set_last_audio(self, path):
        self.last_audio_path = path

    def stop_tts_task(self):
        stop_event.set()
        self.tts_log_write("🛑 Zadanie oznaczone do zatrzymania.")

    def reset_app(self):
        self.root.destroy()
        exe = sys.argv[0]
        if exe.lower().endswith(".exe") and os.path.exists(exe):
            subprocess.Popen([exe] + sys.argv[1:])
        else:
            subprocess.Popen([sys.executable] + sys.argv)
        sys.exit()

    def tts_log_write(self, msg):
        self.tts_log.insert("end", msg + "\n")
        self.tts_log.see("end")
        self.tts_log.update_idletasks()

    def save_settings_from_gui(self):
        settings = {
            "engine": self.engine_var.get(),
            "voice_id": self.selected_voice_id,
            "eleven_api_key": self.eleven_api_var.get(),
            "eleven_voice_id": self.eleven_voice_var.get(),
            "tempo": self.tts_tempo_var.get(),
            "pitch": self.tts_pitch_var.get(),
            "gain": self.tts_gain_var.get(),
            "format": self.fmt_var.get(),
            "merge": self.merge_var.get(),
            "output_dir": self.out_var.get(),
            "srt_1s_ciszy": self.srt_1s_ciszy.get(),
            "global_stretch": self.global_stretch_var.get(),
        }
        ok = save_settings(settings, self.settings_path_var.get())
        if ok:
            messagebox.showinfo("Ustawienia", f"Ustawienia zapisane do:\n{self.settings_path_var.get()}")
        else:
            messagebox.showerror("Błąd", f"Nie można zapisać ustawień do:\n{self.settings_path_var.get()}")

    def load_settings_to_gui(self):
        s = self.settings
        if not s: return
        self.engine_var.set(s.get("engine", self.engine_var.get()))
        self.selected_voice_id = s.get("voice_id", "")
        self.eleven_api_var.set(s.get("eleven_api_key", ""))
        self.eleven_voice_var.set(s.get("eleven_voice_id", ""))
        self.tts_tempo_var.set(s.get("tempo", 1.0))
        self.tts_pitch_var.set(s.get("pitch", 1.0))
        self.tts_gain_var.set(s.get("gain", 1.0))
        self.fmt_var.set(s.get("format", DEFAULT_FORMAT))
        self.merge_var.set(s.get("merge", False))
        self.out_var.set(s.get("output_dir", "audio_output"))
        self.srt_1s_ciszy.set(s.get("srt_1s_ciszy", False))
        self.global_stretch_var.set(s.get("global_stretch", False))
        self.sync_merge_and_1s()
        self.on_engine_change()

    def start_batch(self):
        if not self.batch_files:
            messagebox.showerror("Błąd", "Nie dodano żadnych plików do batcha!")
            return
        outdir = self.batch_outdir.get()
        if not outdir or not os.path.isdir(outdir):
            messagebox.showerror("Błąd", "Musisz wybrać istniejący folder wyjściowy audio!")
            return
        speed = self.batch_speed_var.get()
        pitch = self.batch_pitch_var.get()
        gain = self.batch_gain_var.get()
        silence_remove = self.batch_silence_var.get()
        fmt = self.batch_format_var.get()
        start_s = self.batch_start_var.get()
        end_s = self.batch_end_var.get()
        self.batch_log.delete("1.0", "end")
        def log(msg):
            self.batch_log.insert("end", msg + "\n")
            self.batch_log.see("end")
            self.batch_log.update_idletasks()
        threading.Thread(target=batch_audio_task, args=(self.batch_files, outdir, speed, pitch, gain, silence_remove, fmt, start_s, end_s, log), daemon=True).start()

    def batch_log_write(self, msg):
        self.batch_log.insert("end", msg + "\n")
        self.batch_log.see("end")
        self.batch_log.update_idletasks()

    def build_events_tab(self, frame):
        self.add_credit(frame)
        desc = (
            "SpeakVault to zaawansowane narzędzie do generowania mowy z tekstu (TTS) oraz wsadowego przetwarzania plików audio.\n"
            "Działa w systemie Windows i obsługuje polskie i angielskie głosy oraz formaty audio ogg/mp3/wav.\n\n"
            "FUNKCJE:\n"
            "- TTS: Zamiana tekstu (pliki TXT, CSV, SRT) na mowę, z obsługą Google TTS, Windows TTS, ElevenLabs (jeśli dostępne).\n"
            "- Wybór głosu, API, parametrów mowy (tempo, ton, głośność), formatu audio i scalenia do jednego pliku.\n"
            "- Wsadowa obróbka audio: zmiana tempa, tonu, głośności, usuwanie ciszy, konwersja formatów, wycinanie fragmentów.\n"
            "- Odtwarzanie plików audio z poziomu aplikacji.\n"
            "- Zapis i odczyt ustawień w pliku o wybranej nazwie i lokalizacji.\n"
            "- Dziennik zdarzeń: szczegółowe logi wszystkich operacji oraz błędów.\n\n"
            "Jak działa?\n"
            "1. Wybierz plik tekstowy i folder wyjściowy audio.\n"
            "2. Skonfiguruj silnik mowy oraz parametry (głos, API, tempo, ton, głośność, format).\n"
            "3. W razie potrzeby zapisz/odczytaj ustawienia do własnego pliku.\n"
            "4. Kliknij 'Start generowania mowy'.\n"
            "5. Sprawdź log operacji i odtwórz wygenerowany dźwięk.\n"
            "6. W zakładce batch możesz masowo obrabiać pliki audio.\n"
            "7. W każdej chwili możesz sprawdzić dziennik zdarzeń.\n\n"
            "Aplikacja powstała z myślą o twórcach, lektorach, streamerach, nauczycielach oraz wszystkich, którzy chcą szybko tworzyć wysokiej jakości mowę z dowolnego tekstu.\n"
            "Dodatkowe opcje: obsługa zapisu ustawień, logowania błędów, wsparcie dla zaawansowanych silników TTS."
        )
        desc_frame = ttk.Labelframe(frame, text="Opis programu", style="Custom.TLabelframe")
        desc_frame.pack(fill="x", padx=10, pady=(10,2))
        desc_text = tk.Text(desc_frame, height=15, bg="#181e22", fg="#62ffb3", font=("Segoe UI", 10), relief="flat", wrap="word")
        desc_text.insert("end", desc)
        desc_text.config(state="disabled")
        desc_text.pack(fill="x", padx=6, pady=3)

        ttk.Label(frame, text="Dziennik zdarzeń (TTS + batch):", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=7)
        self.events_text = tk.Text(frame, height=23, bg="#181e22", fg="#e6e6e6", font=("Consolas", 10), relief="flat", insertbackground="#e6e6e6")
        self.events_text.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(frame, text="Odśwież", command=self.refresh_events).pack(anchor="e", padx=20, pady=5)
        self.refresh_events()

    def refresh_events(self):
        self.events_text.delete("1.0", "end")
        for line in event_log[-250:]:
            self.events_text.insert("end", line + "\n")
        self.events_text.see("end")

if __name__ == "__main__":
    root = tk.Tk()
    app = SpeakVaultApp(root)
    app.fmt_var.set(DEFAULT_FORMAT)
    app.batch_format_var.set(DEFAULT_FORMAT)
    app.merge_var.set(False)
    app.srt_1s_ciszy.set(False)
    app.global_stretch_var.set(False)
    root.mainloop()