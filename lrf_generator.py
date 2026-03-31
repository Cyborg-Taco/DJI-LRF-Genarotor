import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import queue
import uuid

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

class LRFGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DJI LRF Generator & Replacer")
        self.root.geometry("650x550")
        
        # Setup clean styling
        style = ttk.Style()
        style.theme_use('clam')
        
        self.task_queue = queue.Queue()
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        
        self.active_progress = {}
        
        self.setup_ui()
        
        # Start a pool of worker threads
        self.num_workers = 3
        self.workers = []
        for _ in range(self.num_workers):
            t = threading.Thread(target=self.worker_loop, daemon=True)
            t.start()
            self.workers.append(t)
        
        # Start GUI log & progress updater
        self.root.after(100, self.process_queues)
        
        if not YTDLP_AVAILABLE:
            self.log("WARNING: 'yt-dlp' is not installed. YouTube downloads won't work.")
            self.log("Install yt-dlp by running: pip install yt-dlp")
            
        self.log("Application started. Ready to add tasks.")

    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- Top Control Form ---
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Clone Section
        clone_frame = ttk.LabelFrame(control_frame, text="1. Clone Local File", padding="10")
        clone_frame.pack(fill=tk.X, pady=5)
        
        lbl_clone = ttk.Label(clone_frame, text="Replace a target file with another local video file.")
        lbl_clone.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_clone = ttk.Button(clone_frame, text="Select Files & Add to Queue", command=self.add_clone_task)
        btn_clone.pack(side=tk.RIGHT)
        
        # YouTube Section
        yt_frame = ttk.LabelFrame(control_frame, text="2. Download from YouTube", padding="10")
        yt_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(yt_frame, text="YouTube URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        yt_entry = ttk.Entry(yt_frame, textvariable=self.url_var, width=40)
        yt_entry.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        btn_yt = ttk.Button(yt_frame, text="Download & Add to Queue", command=self.add_youtube_task)
        btn_yt.pack(side=tk.RIGHT)
        
        # --- Options Section ---
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=(5, 5))
        
        self.encode_lrf_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Transcode video for .LRF (Prevents playback stuttering on DJI)", variable=self.encode_lrf_var).pack(side=tk.LEFT, padx=5)

        # --- Progress Bar Section ---
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(5, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, expand=True)
        
        # --- Bottom Status Log ---
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED, bg="#f5f5f5", fg="#333", height=12)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def log(self, message):
        """Thread-safe way to add messages to the GUI."""
        self.log_queue.put(message)
        
    def set_progress(self, task_id, percent):
        """Thread-safe way to update the progress bar."""
        self.progress_queue.put({'id': task_id, 'percent': percent})
        
    def process_queues(self):
        """Check for new log messages and progress updates and act on them safely."""
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
            
        while not self.progress_queue.empty():
            data = self.progress_queue.get()
            tid = data['id']
            val = data['percent']
            
            if val < 0:
                self.active_progress.pop(tid, None)
            else:
                self.active_progress[tid] = val
                
        if self.active_progress:
            avg_progress = sum(self.active_progress.values()) / len(self.active_progress)
            self.progress_var.set(avg_progress)
        else:
            self.progress_var.set(0)
            
        # Re-schedule check
        self.root.after(100, self.process_queues)

    def get_file_path(self, title="Select a file", filetypes=(("MP4 files", "*.mp4"), ("All files", "*.*"))):
        return filedialog.askopenfilename(title=title, filetypes=filetypes)

    def add_clone_task(self):
        source = self.get_file_path(title="1. Select SOURCE video (the file you want to copy)")
        if not source:
            return
            
        target = self.get_file_path(title="2. Select TARGET video to replace")
        if not target:
            return
            
        task_id = uuid.uuid4().hex[:8]
        self.task_queue.put({'id': task_id, 'type': 'clone', 'source': source, 'target': target, 'encode_lrf': self.encode_lrf_var.get()})
        self.log(f"-> QUEUED: Replace '{os.path.basename(target)}' with local '{os.path.basename(source)}' [Task {task_id}]")

    def add_youtube_task(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Please enter a valid YouTube URL.")
            return
            
        target = self.get_file_path(title="Select TARGET video to replace")
        if not target:
            return
            
        task_id = uuid.uuid4().hex[:8]
        self.task_queue.put({'id': task_id, 'type': 'youtube', 'source': url, 'target': target, 'encode_lrf': self.encode_lrf_var.get()})
        self.log(f"-> QUEUED: Replace '{os.path.basename(target)}' with downloaded YouTube video [Task {task_id}]")
        self.url_var.set("") # Clear URL bar after adding
        
    def worker_loop(self):
        """Background thread that continuously grabs items from the queue and processes them."""
        while True:
            task = self.task_queue.get()
            if task is None:
                break
            self.process_task(task)
            self.task_queue.task_done()
            self.set_progress(task['id'], -1) # Reset/remove progress when done

    class YTDLPLogger:
        def __init__(self, log_func):
            self.log_func = log_func
        def debug(self, msg):
            pass
        def info(self, msg):
            pass
        def warning(self, msg):
            if "JavaScript runtime" not in msg:
                self.log_func(f"[yt-dlp trace] {msg}")
        def error(self, msg):
            self.log_func(f"[yt-dlp error] {msg}")

    def yt_progress_hook(self, task_id, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                downloaded = d.get('downloaded_bytes', 0)
                percent = (downloaded / total) * 100
                self.set_progress(task_id, percent)
        elif d['status'] == 'finished':
            self.set_progress(task_id, 100)

    def download_youtube_video(self, task_id, url, output_path):
        if not YTDLP_AVAILABLE:
            self.log("[Worker] Error: yt-dlp is not installed. Please run: pip install yt-dlp")
            return False
            
        temp_output = output_path + ".tempdl"
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best',
            'concurrent_fragment_downloads': 5,
            'outtmpl': temp_output,
            'quiet': True,
            'noprogress': True,
            'source_address': '0.0.0.0',
            'logger': self.YTDLPLogger(self.log),
            'progress_hooks': [lambda d: self.yt_progress_hook(task_id, d)],
            'merge_output_format': 'mp4'
        }
        
        try:
            self.set_progress(task_id, 0)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            actual_temp = temp_output
            if not os.path.exists(actual_temp) and os.path.exists(temp_output + ".mp4"):
                actual_temp = temp_output + ".mp4"
                
            if os.path.exists(actual_temp):
                if os.path.exists(output_path):
                    os.remove(output_path)
                shutil.move(actual_temp, output_path)
                return True
            else:
                self.log("[Worker] Error: Downloaded temp file could not be found.")
                return False
        except Exception as e:
            self.log(f"[Worker] YouTube download failed: {e}")
            return False

    def copy_file_with_progress(self, task_id, src, dst):
        """Custom copy function that pushes updates to a progress bar."""
        total_size = os.path.getsize(src)
        copied = 0
        chunk_size = 1024 * 1024 * 4 # 4MB chunks
        
        self.set_progress(task_id, 0)
        with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)
                if total_size > 0:
                    self.set_progress(task_id, (copied / total_size) * 100)
                    
        # Copy metadata
        shutil.copystat(src, dst)

    def process_task(self, task):
        target_path = task['target']
        task_id = task['id']
        
        if not target_path or not os.path.exists(target_path):
            self.log(f"[Worker] Error: Target path '{target_path}' does not exist.")
            return False
            
        target_dir = os.path.dirname(target_path)
        target_name, target_ext = os.path.splitext(os.path.basename(target_path))
        
        lrf_path = os.path.join(target_dir, target_name + ".LRF")
        if not os.path.exists(lrf_path):
            lrf_path_lower = os.path.join(target_dir, target_name + ".lrf")
            if os.path.exists(lrf_path_lower):
                lrf_path = lrf_path_lower

        try:
            if task['type'] == 'youtube':
                self.log(f"\n[Worker] Downloading from YouTube to {os.path.basename(target_path)}...")
                success = self.download_youtube_video(task_id, task['source'], target_path)
                if not success:
                    return False
            else:
                source_path = task['source']
                self.log(f"\n[Worker] Copying {os.path.basename(source_path)} to {os.path.basename(target_path)}...")
                
                # We do custom copy so we get progress bar updates instead of blocking silently
                if os.path.exists(target_path):
                    os.remove(target_path)
                self.copy_file_with_progress(task_id, source_path, target_path)
                
            if os.path.exists(lrf_path):
                self.log(f"[Worker] Deleting existing LRF file: {os.path.basename(lrf_path)}")
                os.remove(lrf_path)
                
            new_lrf_path = os.path.join(target_dir, target_name + ".LRF")
            self.log(f"[Worker] Creating new LRF file wrapper: {os.path.basename(new_lrf_path)}")
            
            if task.get('encode_lrf', True) and shutil.which("ffmpeg"):
                self.log(f"[Worker] Transcoding to DJI proxy format (720p, 2Mbps) with FFmpeg. This may take a moment...")
                import subprocess
                cmd = [
                    "ffmpeg", "-y", "-i", target_path,
                    "-vf", "scale=-2:720,format=yuv420p", "-c:v", "libx264", "-b:v", "2M",
                    "-preset", "fast", "-r", "30",
                    "-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-ac", "2", 
                    "-f", "mp4", new_lrf_path
                ]
                try:
                    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.set_progress(task_id, 100)
                except subprocess.CalledProcessError as e:
                    self.log(f"[Worker] FFmpeg formatting failed. Error output:")
                    for line in e.stderr.splitlines()[-5:]: # Print last 5 lines for context
                        self.log(f"   {line}")
                    self.log(f"[Worker] Falling back to simple file copy.")
                    self.copy_file_with_progress(task_id, target_path, new_lrf_path)
            else:
                if not task.get('encode_lrf', True):
                    self.log(f"[Worker] Transcoding skipped via UI toggle. Copying file directly.")
                else:
                    self.log(f"[Worker] FFmpeg not found! Falling back to simple file copy. WARNING: This may cause video stuttering on DJI hardware.")
                self.copy_file_with_progress(task_id, target_path, new_lrf_path)
            
            self.log(f"[Worker] Finished processing {os.path.basename(target_path)}!")
            return True
        except Exception as e:
            self.log(f"[Worker] Error processing {target_path}: {e}")
            return False

if __name__ == "__main__":
    root = tk.Tk()
    app = LRFGeneratorApp(root)
    root.mainloop()
