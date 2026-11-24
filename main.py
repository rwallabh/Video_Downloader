#!/usr/bin/env python3
"""
Universal Video Downloader
--------------------------
A CLI + GUI wrapper around yt-dlp, which supports 1,800+ sites and has a
generic extractor for pages with embedded video / direct media links.

Setup:
    pip install -U yt-dlp
    (optional but recommended) install ffmpeg for merging video+audio and MP3 extraction

Usage:
    python video_downloader.py                      # opens the GUI
    python video_downloader.py URL [URL ...]        # CLI
    python video_downloader.py URL -q 720           # max 720p
    python video_downloader.py URL -a               # audio only (MP3)
    python video_downloader.py URL --playlist       # download whole playlist
    python video_downloader.py URL -q 2160          # up to 4K (saved as MKV)
    python video_downloader.py URL --list-formats   # see which resolutions the site offers
    python video_downloader.py URL --cookies-from-browser chrome   # login-required videos you have access to

Only download content you own, that is in the public domain / freely licensed,
or that you otherwise have permission to download. Respect each site's terms.
DRM-protected streams (Netflix, Disney+, etc.) are not supported.
"""

import argparse
import shutil
import sys
import threading
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -U yt-dlp")

HAS_FFMPEG = shutil.which("ffmpeg") is not None
QUALITIES = ["best", "2160", "1440", "1080", "720", "480", "360"]


def build_options(outdir, quality="best", audio_only=False, playlist=False,
                  cookies_browser=None, cookies_file=None, hook=None, logger=None,
                  container="auto"):
    outdir = Path(outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    # 1440p / 4K / "best" are normally VP9 or AV1 video + Opus audio, which play
    # reliably in MKV. 1080p and below: prefer H.264 + AAC in MP4 (plays everywhere).
    high_res = quality in ("best", "1440", "2160")
    if container == "auto":
        container = "mkv" if high_res else "mp4"

    if audio_only:
        fmt = "bestaudio/best"
    elif quality == "best":
        fmt = "bv*+ba/b" if HAS_FFMPEG else "b"
    else:
        h = int(quality)
        fmt = (f"bv*[height<={h}]+ba/b[height<={h}]" if HAS_FFMPEG
               else f"b[height<={h}]/b")

    opts = {
        "format": fmt,
        "outtmpl": str(outdir / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": not playlist,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": True,
    }
    if HAS_FFMPEG and not audio_only:
        opts["merge_output_format"] = container
        if container == "mp4":
            # highest resolution first, then prefer H.264/AAC so the MP4 plays everywhere
            opts["format_sort"] = ["res", "vcodec:h264", "acodec:aac", "ext:mp4:m4a"]
    if audio_only and HAS_FFMPEG:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if hook:
        opts["progress_hooks"] = [hook]
    if logger:
        opts["logger"] = logger
    return opts


def download(urls, **kwargs):
    """Download one or more URLs. Returns the number of failures."""
    failures = 0
    with yt_dlp.YoutubeDL(build_options(**kwargs)) as ydl:
        for url in urls:
            try:
                info = ydl.extract_info(url, download=True)
                if info and info.get("height"):
                    print(f"  Resolution: {info.get('width')}x{info['height']} "
                          f"({info.get('vcodec', '?').split('.')[0]})")
            except yt_dlp.utils.DownloadError as e:
                failures += 1
                print(f"\n[error] {url}\n        {e}", file=sys.stderr)
    return failures


def list_formats(url, cookies_browser=None, cookies_file=None):
    """Print every resolution/codec the site offers for this URL."""
    o = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if cookies_browser:
        o["cookiesfrombrowser"] = (cookies_browser,)
    if cookies_file:
        o["cookiefile"] = cookies_file
    with yt_dlp.YoutubeDL(o) as ydl:
        info = ydl.extract_info(url, download=False)
    print(f"{info.get('title')}\n")
    print(f"{'ID':<10}{'EXT':<6}{'RESOLUTION':<12}{'FPS':<5}{'VCODEC':<14}{'ACODEC':<12}")
    for f in info.get("formats", []):
        res = f"{f.get('width') or '?'}x{f.get('height') or '?'}" if f.get("height") else "audio"
        print(f"{str(f.get('format_id')):<10}{str(f.get('ext')):<6}{res:<12}"
              f"{str(f.get('fps') or ''):<5}{str(f.get('vcodec', ''))[:12]:<14}"
              f"{str(f.get('acodec', ''))[:10]:<12}")
    best = max((f.get("height") or 0 for f in info.get("formats", [])), default=0)
    print(f"\nHighest resolution available: {best}p")


# ----------------------------- CLI ---------------------------------------

def cli_hook(d):
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        eta = d.get("_eta_str", "").strip()
        print(f"\r  {pct:>7}  {speed:>12}  ETA {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\r  Downloaded: {Path(d['filename']).name}" + " " * 20)


def run_cli(args):
    if args.list_formats:
        for u in args.urls:
            list_formats(u, args.cookies_from_browser, args.cookies)
        return
    if not HAS_FFMPEG and args.quality in ("best", "2160", "1440", "1080"):
        print("[WARNING] ffmpeg was not found. Full HD / 2K / 4K are delivered as separate "
              "video and audio streams, so without ffmpeg you will only get ~720p or lower.\n"
              "          Install it: Windows  winget install ffmpeg | macOS  brew install ffmpeg "
              "| Linux  sudo apt install ffmpeg\n")
    failures = download(
        args.urls,
        outdir=args.output,
        quality=args.quality,
        audio_only=args.audio,
        playlist=args.playlist,
        cookies_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        hook=cli_hook,
        container=args.container,
    )
    sys.exit(1 if failures else 0)


# ----------------------------- GUI ---------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("Universal Video Downloader")
    root.geometry("640x460")

    url_var = tk.StringVar()
    dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
    qual_var = tk.StringVar(value="best")
    audio_var = tk.BooleanVar(value=False)
    list_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="Ready")

    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="Video URL").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=url_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

    ttk.Label(frm, text="Save to").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=dir_var).grid(row=1, column=1, sticky="ew", pady=4)
    ttk.Button(frm, text="Browse…",
               command=lambda: dir_var.set(filedialog.askdirectory() or dir_var.get())
               ).grid(row=1, column=2, padx=(6, 0))

    ttk.Label(frm, text="Max quality").grid(row=2, column=0, sticky="w", pady=4)
    qrow = ttk.Frame(frm)
    qrow.grid(row=2, column=1, sticky="w", pady=4)
    ttk.Combobox(qrow, textvariable=qual_var, values=QUALITIES, width=8,
                 state="readonly").pack(side="left")
    ttk.Label(qrow, text="  Format").pack(side="left")
    cont_var = tk.StringVar(value="auto")
    ttk.Combobox(qrow, textvariable=cont_var, values=["auto", "mp4", "mkv"], width=6,
                 state="readonly").pack(side="left", padx=(4, 0))

    opts = ttk.Frame(frm)
    opts.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
    ttk.Checkbutton(opts, text="Audio only (MP3)", variable=audio_var).pack(side="left", padx=(0, 16))
    ttk.Checkbutton(opts, text="Download full playlist", variable=list_var).pack(side="left")

    btn = ttk.Button(frm, text="Download")
    btn.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")

    bar = ttk.Progressbar(frm, maximum=100)
    bar.grid(row=5, column=0, columnspan=3, sticky="ew")
    ttk.Label(frm, textvariable=status_var).grid(row=6, column=0, columnspan=3, sticky="w", pady=4)

    log = tk.Text(frm, height=10, state="disabled", wrap="word")
    log.grid(row=7, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(7, weight=1)

    def log_line(msg):
        def _do():
            log.configure(state="normal")
            log.insert("end", msg + "\n")
            log.see("end")
            log.configure(state="disabled")
        root.after(0, _do)

    class GuiLogger:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m): log_line(f"[warn] {m}")
        def error(self, m): log_line(f"[error] {m}")

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                root.after(0, lambda: bar.configure(value=d["downloaded_bytes"] * 100 / total))
            root.after(0, lambda: status_var.set(
                f"{d.get('_percent_str', '').strip()}  {d.get('_speed_str', '').strip()}  "
                f"ETA {d.get('_eta_str', '').strip()}"))
        elif d["status"] == "finished":
            log_line(f"Downloaded: {Path(d['filename']).name}")

    def worker(url):
        try:
            fails = download([url], outdir=dir_var.get(), quality=qual_var.get(),
                             audio_only=audio_var.get(), playlist=list_var.get(),
                             hook=hook, logger=GuiLogger(), container=cont_var.get())
            root.after(0, lambda: status_var.set("Failed" if fails else "Done ✔"))
        except Exception as e:  # noqa: BLE001
            log_line(f"[error] {e}")
            root.after(0, lambda: status_var.set("Failed"))
        finally:
            root.after(0, lambda: btn.configure(state="normal"))

    def start():
        url = url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a video URL first.")
            return
        if not HAS_FFMPEG and qual_var.get() in ("best", "2160", "1440", "1080"):
            if not messagebox.askyesno(
                    "ffmpeg not found",
                    "Full HD / 4K need ffmpeg to merge video and audio.\n"
                    "Without it you will only get ~720p or lower.\n\nContinue anyway?"):
                return
        btn.configure(state="disabled")
        bar.configure(value=0)
        status_var.set("Starting…")
        threading.Thread(target=worker, args=(url,), daemon=True).start()

    btn.configure(command=start)
    root.mainloop()


# ----------------------------- main --------------------------------------

def main():
    p = argparse.ArgumentParser(description="Download videos from (almost) any website.")
    p.add_argument("urls", nargs="*", help="Video page URLs or direct media links")
    p.add_argument("-o", "--output", default=str(Path.home() / "Downloads"), help="Output folder")
    p.add_argument("-q", "--quality", default="best", choices=QUALITIES,
                   help="Maximum video height (default: best)")
    p.add_argument("-a", "--audio", action="store_true", help="Extract audio only (MP3)")
    p.add_argument("--playlist", action="store_true", help="Download entire playlist if URL is one")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="Use your browser's login cookies (chrome, firefox, edge, safari…)")
    p.add_argument("--cookies", metavar="FILE", help="Netscape-format cookies.txt file")
    p.add_argument("--container", default="auto", choices=["auto", "mp4", "mkv"],
                   help="Output container. auto = mkv for 1440p/4K/best, mp4 for 1080p and below")
    p.add_argument("--list-formats", action="store_true",
                   help="Show available resolutions/codecs for the URL and exit")
    args = p.parse_args()

    if not args.urls:
        run_gui()
    else:
        run_cli(args)


if __name__ == "__main__":
    main()