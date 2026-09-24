#!/usr/bin/env python3
"""
Round 2: realistic pipeline test.
Real videos of the genre these bots actually process. Tries a strategy chain per video,
records which strategy wins, how long it took, and whether behaviour degrades over a burst.
"""
import json, os, subprocess, time, glob, tempfile, urllib.request, urllib.error

# (id, label, duration_sec, note)
VIDEOS = [
    ("vAsA_t_5a-I", "news clip 3min",        174,  "captions"),
    ("Xi0fKbOz9ZA", "Netanyahu ABC 16min",   970,  "captions"),
    ("ZG05bAvq9PY", "Netanyahu full 22min",  1322, "captions"),
    ("dBDww47UKSM", "Senate hearing 71min",  4299, "NO CAPTIONS"),
    ("02Ns6EbCplY", "Amanpour podcast 95min",5721, "captions"),
    ("-H50QxEApYg", "Rubio testimony 159min",9558, "long"),
    ("sflvFeqAsBE", "SFRC hearing 134min",   8055, "long"),
    ("OCdrhALAAPM", "Hebrew news 15min",     909,  "hebrew"),
    ("ofOQYgsqjYg", "Hebrew interview 6min", 367,  "hebrew"),
    ("xiXsDPguMgc", "Arabic al-Sharaa 45min",2753, "arabic"),
]
LANGS = "en.*,en,en-orig,iw,he,ar"
rows = []

def run(cmd, timeout=300):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"

def vtt_text(path):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")) or line.isdigit():
            continue
        out.append(line)
    return " ".join(out)

# --- strategies, in the order a real pipeline would try them ---
def s_ytdlp(vid, client=None):
    d = tempfile.mkdtemp()
    cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
           "--sub-langs", LANGS, "--sub-format", "vtt/best", "--no-warnings", "--no-playlist",
           "-o", os.path.join(d, "%(id)s.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
    if client:
        cmd[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    code, out, err = run(cmd)
    f = glob.glob(os.path.join(d, "*.vtt"))
    if f:
        t = vtt_text(f[0])
        if len(t) > 100:
            return True, len(t), os.path.basename(f[0])
    e = [l for l in (err or "").splitlines() if "ERROR" in l]
    return False, 0, (e[0][:120] if e else "no subs found")

def s_yta(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return False, 0, "not installed"
    try:
        api = YouTubeTranscriptApi()
        tl = api.list(vid)
        tr = None
        for pref in (["en"], ["iw", "he"], ["ar"]):
            try:
                tr = tl.find_transcript(pref); break
            except Exception: pass
        if tr is None:
            tr = next(iter(tl))
        txt = " ".join(s.text for s in tr.fetch())
        return (len(txt) > 100), len(txt), "ok"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {str(e)[:100]}"

def s_audio(vid, seconds=None):
    """Download audio (optionally only first N sec) — the Whisper path."""
    d = tempfile.mkdtemp()
    cmd = ["yt-dlp", "-f", "bestaudio/best", "--no-warnings", "--no-playlist",
           "-x", "--audio-format", "mp3", "--audio-quality", "9",
           "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
           "-o", os.path.join(d, "a.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
    if seconds:
        cmd[1:1] = ["--download-sections", f"*0-{seconds}"]
    code, out, err = run(cmd, timeout=600)
    f = glob.glob(os.path.join(d, "a.mp3")) or glob.glob(os.path.join(d, "a.*"))
    if f and os.path.getsize(f[0]) > 10000:
        mb = os.path.getsize(f[0]) / 1e6
        return True, int(os.path.getsize(f[0])), f"{mb:.1f}MB mp3"
    e = [l for l in (err or "").splitlines() if "ERROR" in l]
    return False, 0, (e[0][:120] if e else "no file")

CHAIN = [
    ("yt-dlp default",      lambda v: s_ytdlp(v)),
    ("yt-dlp android_vr",   lambda v: s_ytdlp(v, "android_vr")),
    ("yt-dlp android",      lambda v: s_ytdlp(v, "android")),
    ("youtube-transcript-api", s_yta),
]

env = os.environ.get("PROBE_ENV", "unknown")
try:
    ip = urllib.request.urlopen("https://api.ipify.org", timeout=20).read().decode()
except Exception:
    ip = "unknown"
code, ver, _ = run(["yt-dlp", "--version"], 30)
print(f"\n{'='*104}\nROUND 2 — {env}   IP={ip}   yt-dlp={ver.strip()}\n{'='*104}\n", flush=True)

t_start = time.time()
for idx, (vid, label, dur, note) in enumerate(VIDEOS, 1):
    print(f"\n--- [{idx}/{len(VIDEOS)}] {label}  ({dur//60}min, {note})  {vid} ---", flush=True)
    winner, chars, detail, elapsed = None, 0, "", 0
    for name, fn in CHAIN:
        t0 = time.time()
        ok, n, d = fn(vid)
        dt = time.time() - t0
        print(f"      {'PASS' if ok else 'FAIL'}  {name:26s} {dt:6.1f}s  {n:<8} {d}", flush=True)
        if ok:
            winner, chars, detail, elapsed = name, n, d, dt
            break
    rows.append({"video": vid, "label": label, "dur_min": dur // 60, "note": note,
                 "winner": winner, "chars": chars, "detail": detail, "sec": round(elapsed, 1)})

# caption-less video: prove the audio/Whisper leg
print(f"\n\n--- AUDIO PATH (Whisper fallback) on the caption-less hearing ---", flush=True)
t0 = time.time()
ok, n, d = s_audio("dBDww47UKSM", seconds=300)   # first 5 min, to size it
print(f"      {'PASS' if ok else 'FAIL'}  audio 5min slice   {time.time()-t0:6.1f}s  {d}", flush=True)
rows.append({"video": "dBDww47UKSM", "label": "audio 5min slice", "winner": "audio-dl" if ok else None,
             "chars": n, "detail": d, "sec": round(time.time()-t0, 1)})

t0 = time.time()
ok2, n2, d2 = s_audio("dBDww47UKSM")             # full 71 min
print(f"      {'PASS' if ok2 else 'FAIL'}  audio FULL 71min   {time.time()-t0:6.1f}s  {d2}", flush=True)
rows.append({"video": "dBDww47UKSM", "label": "audio full 71min", "winner": "audio-dl" if ok2 else None,
             "chars": n2, "detail": d2, "sec": round(time.time()-t0, 1)})

total = time.time() - t_start
ok_n = sum(1 for r in rows if r["winner"])
print(f"\n{'='*104}\nSUMMARY — {env}  ({ok_n}/{len(rows)} succeeded, {total/60:.1f} min total)\n{'='*104}", flush=True)
for r in rows:
    w = r["winner"] or "*** ALL FAILED ***"
    print(f"  {r['label']:26s} {str(r.get('dur_min','')):>4}min  {w:26s} {r['chars']:<9} {r['detail'][:46]}", flush=True)

with open(os.environ.get("PROBE_OUT", "/tmp/probe2.json"), "w") as f:
    json.dump({"env": env, "ip": ip, "rows": rows}, f, indent=2)
