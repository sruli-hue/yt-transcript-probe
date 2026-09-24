#!/usr/bin/env python3
"""
Probe: which free methods can fetch a YouTube transcript from THIS machine's IP?
Run locally (residential) and on GitHub Actions (datacenter) and diff the results.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error, tempfile, glob, re

VIDEOS = {
    "short_captioned": "dQw4w9WgXcQ",   # stable, auto+manual captions
    "news_interview":  "5_XSYlAfJZM",   # news-style, ~long
}
TIMEOUT = 120
results = []

def rec(strategy, video, ok, detail, chars=0):
    results.append({"strategy": strategy, "video": video, "ok": ok,
                    "chars": chars, "detail": str(detail)[:400]})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {strategy:38s} {video:18s} chars={chars:<7} {str(detail)[:150]}", flush=True)

def run(cmd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"

# ---------- 1. yt-dlp subtitle fetch, across player clients ----------
CLIENTS = ["default", "tv", "tv_simply", "web_embedded", "android_vr",
           "ios", "mweb", "web", "web_safari", "android"]

def ytdlp_subs(vid, client):
    d = tempfile.mkdtemp()
    cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
           "--sub-langs", "en.*,en,iw,ar", "--sub-format", "vtt/srt/best",
           "--no-warnings", "--no-playlist",
           "-o", os.path.join(d, "%(id)s.%(ext)s"),
           f"https://www.youtube.com/watch?v={vid}"]
    if client != "default":
        cmd[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    code, out, err = run(cmd)
    files = glob.glob(os.path.join(d, "*.vtt")) + glob.glob(os.path.join(d, "*.srt"))
    if files:
        txt = open(files[0], encoding="utf-8", errors="replace").read()
        return True, len(txt), f"got {os.path.basename(files[0])}"
    errline = [l for l in (err or "").splitlines() if "ERROR" in l or "bot" in l.lower()]
    return False, 0, (errline[0] if errline else (err or out or "no subs")).strip()

# ---------- 2. youtube-transcript-api ----------
def yta(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return False, 0, "library not installed"
    try:
        try:                       # v1.x API
            api = YouTubeTranscriptApi()
            fetched = api.fetch(vid, languages=["en", "iw", "ar"])
            txt = " ".join(s.text for s in fetched)
        except AttributeError:     # v0.x API
            segs = YouTubeTranscriptApi.get_transcript(vid, languages=["en", "iw", "ar"])
            txt = " ".join(s["text"] for s in segs)
        return True, len(txt), "ok"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"

# ---------- 3. direct timedtext endpoint (URL harvested via yt-dlp -J) ----------
def timedtext(vid, client="default"):
    cmd = ["yt-dlp", "-J", "--skip-download", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"]
    if client != "default":
        cmd[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    code, out, err = run(cmd)
    if code != 0 or not out.strip():
        return False, 0, f"metadata fetch failed: {(err or '')[:150]}"
    try:
        info = json.loads(out)
    except Exception as e:
        return False, 0, f"bad json {e}"
    subs = {**(info.get("automatic_captions") or {}), **(info.get("subtitles") or {})}
    url = None
    for lang in ("en", "en-orig", "iw", "ar"):
        for k, v in subs.items():
            if k.startswith(lang) and v:
                url = v[0].get("url"); break
        if url: break
    if not url:
        return False, 0, "no caption track in metadata"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        return (len(body) > 50), len(body), f"HTTP 200, {len(body)}B"
    except urllib.error.HTTPError as e:
        return False, 0, f"HTTP {e.code}"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"

# ---------- 4. InnerTube direct POST ----------
INNERTUBE = {
    "ANDROID":  {"clientName": "ANDROID",  "clientVersion": "20.10.38", "androidSdkVersion": 30},
    "IOS":      {"clientName": "IOS",      "clientVersion": "20.10.4",  "deviceModel": "iPhone16,2"},
    "TVHTML5":  {"clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER", "clientVersion": "2.0"},
    "WEB":      {"clientName": "WEB",      "clientVersion": "2.20250312.04.00"},
    "MWEB":     {"clientName": "MWEB",     "clientVersion": "2.20250311.03.00"},
}
def innertube(vid, name):
    ctx = INNERTUBE[name]
    payload = json.dumps({"videoId": vid, "context": {"client": {**ctx, "hl": "en", "gl": "US"}},
                          "contentCheckOk": True, "racyCheckOk": True}).encode()
    url = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 12) gzip"
                      if name == "ANDROID" else "Mozilla/5.0",
    })
    try:
        body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        data = json.loads(body)
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"
    status = (data.get("playabilityStatus") or {}).get("status")
    tracks = (((data.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {})
              .get("captionTracks") or [])
    if not tracks:
        return False, 0, f"playability={status}, no captionTracks"
    curl = tracks[0].get("baseUrl")
    try:
        req2 = urllib.request.Request(curl, headers={"User-Agent": "Mozilla/5.0"})
        cap = urllib.request.urlopen(req2, timeout=60).read().decode("utf-8", "replace")
        return (len(cap) > 50), len(cap), f"playability={status}, caption {len(cap)}B"
    except urllib.error.HTTPError as e:
        return False, 0, f"playability={status}, caption HTTP {e.code}"
    except Exception as e:
        return False, 0, f"playability={status}, caption {type(e).__name__}"

# ---------- 5. audio download (for the Whisper fallback path) ----------
def audio_dl(vid, client="default"):
    d = tempfile.mkdtemp()
    cmd = ["yt-dlp", "-f", "bestaudio", "--no-warnings", "--no-playlist",
           "--download-sections", "*0-60", "--force-keyframes-at-cuts",
           "-o", os.path.join(d, "a.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
    if client != "default":
        cmd[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    code, out, err = run(cmd, timeout=180)
    files = [f for f in glob.glob(os.path.join(d, "a.*"))]
    if files and os.path.getsize(files[0]) > 10000:
        return True, os.path.getsize(files[0]), f"downloaded {os.path.basename(files[0])}"
    errline = [l for l in (err or "").splitlines() if "ERROR" in l]
    return False, 0, (errline[0] if errline else "no file").strip()

# =======================  RUN  =======================
env = os.environ.get("PROBE_ENV", "unknown")
print(f"\n{'='*100}\nPROBE ENVIRONMENT: {env}\n{'='*100}\n", flush=True)
code, out, _ = run(["yt-dlp", "--version"], 30)
print(f"yt-dlp version: {out.strip()}\n", flush=True)
try:
    ip = urllib.request.urlopen("https://api.ipify.org", timeout=20).read().decode()
    print(f"public IP: {ip}\n", flush=True)
except Exception as e:
    print(f"public IP: unknown ({e})\n", flush=True)

vid = VIDEOS["short_captioned"]

print("--- 1. yt-dlp subtitles by player_client ---", flush=True)
for c in CLIENTS:
    ok, n, d = ytdlp_subs(vid, c); rec(f"yt-dlp subs client={c}", vid, ok, d, n)

print("\n--- 2. youtube-transcript-api ---", flush=True)
ok, n, d = yta(vid); rec("youtube-transcript-api", vid, ok, d, n)

print("\n--- 3. timedtext direct (url via yt-dlp -J) ---", flush=True)
for c in ["default", "tv", "android_vr", "web_embedded"]:
    ok, n, d = timedtext(vid, c); rec(f"timedtext via client={c}", vid, ok, d, n)

print("\n--- 4. InnerTube direct POST ---", flush=True)
for name in INNERTUBE:
    ok, n, d = innertube(vid, name); rec(f"innertube {name}", vid, ok, d, n)

print("\n--- 5. audio download (Whisper path) ---", flush=True)
for c in ["default", "tv", "android_vr", "ios"]:
    ok, n, d = audio_dl(vid, c); rec(f"audio-dl client={c}", vid, ok, d, n)

# second video, only on strategies that passed
print("\n--- 6. confirm winners on a second video ---", flush=True)
winners = sorted({r["strategy"] for r in results if r["ok"]})
v2 = VIDEOS["news_interview"]
for w in winners:
    if w.startswith("yt-dlp subs client="):
        c = w.split("=")[1]; ok, n, d = ytdlp_subs(v2, c)
    elif w == "youtube-transcript-api":
        ok, n, d = yta(v2)
    elif w.startswith("timedtext via client="):
        c = w.split("=")[1]; ok, n, d = timedtext(v2, c)
    elif w.startswith("innertube "):
        ok, n, d = innertube(v2, w.split()[1])
    elif w.startswith("audio-dl client="):
        c = w.split("=")[1]; ok, n, d = audio_dl(v2, c)
    else:
        continue
    rec(f"[v2] {w}", v2, ok, d, n)

print(f"\n{'='*100}\nSUMMARY ({env})\n{'='*100}", flush=True)
for r in results:
    print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['strategy']:38s} {r['chars']:<8} {r['detail'][:90]}", flush=True)
out_path = os.environ.get("PROBE_OUT", f"/tmp/probe_{env}.json")
with open(out_path, "w") as f:
    json.dump({"env": env, "results": results}, f, indent=2)
print(f"\nwrote {out_path}", flush=True)
