#!/usr/bin/env python3
"""
Round 3 — resolve the round1/round2 contradiction.
Round 1 (video dQw4w9WgXcQ): everything PASSED from Actions.
Round 2 (10 real videos, 3 concurrent runners): everything FAILED, "not a bot", instantly.

Competing explanations:
  (A) dQw4w9WgXcQ is special (hyper-cached) and real videos are always blocked
  (B) the 3x concurrent burst flagged the IP range
  (C) IP reputation drifted between runs
Design: ONE runner, gentle pacing, interleave the round-1 video with a real video.
If dQw4w9WgXcQ passes and the real video fails -> (A).
If both pass -> (B), burst-induced.
If both fail -> (C), range is flagged regardless.
"""
import os, subprocess, tempfile, glob, time, urllib.request, json

CONTROL = ("dQw4w9WgXcQ", "round-1 control (hyper-cached)")
REAL    = ("Xi0fKbOz9ZA", "real news interview 16min")
REAL2   = ("vAsA_t_5a-I", "real news clip 3min")

def run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"

def ytdlp(vid, client=None):
    d = tempfile.mkdtemp()
    cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
           "--sub-langs", "en.*,en", "--sub-format", "vtt/best",
           "--no-warnings", "--no-playlist",
           "-o", os.path.join(d, "%(id)s.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
    if client:
        cmd[1:1] = ["--extractor-args", f"youtube:player_client={client}"]
    c, o, e = run(cmd)
    f = glob.glob(os.path.join(d, "*.vtt"))
    if f:
        return True, os.path.getsize(f[0]), "ok"
    bot = "not a bot" in (e or "")
    er = [l for l in (e or "").splitlines() if "ERROR" in l]
    return False, 0, ("BOT-WALL" if bot else (er[0][:90] if er else "no subs"))

def yta(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        t = " ".join(s.text for s in api.fetch(vid, languages=["en"]))
        return (len(t) > 100), len(t), "ok"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {str(e)[:80]}"

def innertube(vid, name="ANDROID"):
    ctxs = {"ANDROID": {"clientName": "ANDROID", "clientVersion": "20.10.38", "androidSdkVersion": 30},
            "IOS": {"clientName": "IOS", "clientVersion": "20.10.4", "deviceModel": "iPhone16,2"}}
    payload = json.dumps({"videoId": vid, "context": {"client": {**ctxs[name], "hl": "en", "gl": "US"}},
                          "contentCheckOk": True, "racyCheckOk": True}).encode()
    req = urllib.request.Request("https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
        data=payload, headers={"Content-Type": "application/json",
        "User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 12) gzip"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=45).read().decode())
    except Exception as e:
        return False, 0, f"{type(e).__name__}"
    st = (data.get("playabilityStatus") or {}).get("status")
    tr = (((data.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}).get("captionTracks") or [])
    if not tr:
        return False, 0, f"playability={st}, no tracks"
    try:
        cap = urllib.request.urlopen(urllib.request.Request(tr[0]["baseUrl"],
              headers={"User-Agent": "Mozilla/5.0"}), timeout=45).read()
        return len(cap) > 50, len(cap), f"playability={st}"
    except Exception as e:
        return False, 0, f"playability={st}, caption {type(e).__name__}"

STRATS = [("yt-dlp default", lambda v: ytdlp(v)),
          ("yt-dlp android_vr", lambda v: ytdlp(v, "android_vr")),
          ("yt-dlp android", lambda v: ytdlp(v, "android")),
          ("yt-dlp tv_simply", lambda v: ytdlp(v, "tv_simply")),
          ("youtube-transcript-api", yta),
          ("innertube ANDROID", lambda v: innertube(v, "ANDROID")),
          ("innertube IOS", lambda v: innertube(v, "IOS"))]

ip = urllib.request.urlopen("https://api.ipify.org", timeout=20).read().decode()
print(f"\nROUND 3 — single runner, gentle pacing.  IP={ip}\n{'='*92}\n", flush=True)

tally = {}
for vid, label in [CONTROL, REAL, REAL2]:
    print(f"\n### {label}  ({vid})", flush=True)
    for name, fn in STRATS:
        ok, n, d = fn(vid)
        print(f"   {'PASS' if ok else 'FAIL'}  {name:24s} {n:<8} {d}", flush=True)
        tally[(label, name)] = ok
        time.sleep(6)          # gentle: no burst

print(f"\n{'='*92}\nVERDICT INPUTS", flush=True)
for (label, name), ok in tally.items():
    print(f"   {'PASS' if ok else 'FAIL'}  {label:32s} {name}", flush=True)
ctrl = sum(1 for (l, _), o in tally.items() if l == CONTROL[1] and o)
real = sum(1 for (l, _), o in tally.items() if l != CONTROL[1] and o)
print(f"\n   control passes: {ctrl}/{len(STRATS)}   real-video passes: {real}/{len(STRATS)*2}", flush=True)
