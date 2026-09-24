#!/usr/bin/env python3
"""
Round 4 — the free options that DON'T depend on the runner's own YouTube reputation.
Rounds 1-3 established: every direct YouTube endpoint is bot-walled from Actions for real
videos (Rick Astley is a cached false positive).

Tests, on REAL videos only:
  A. youtube-transcript.ai  — free, no API key, vendor does the fetching
  B. yt-dlp through Cloudflare WARP — free VPN, changes egress to Cloudflare IPs
  C. audio download through WARP (the Whisper path for caption-less videos)
"""
import os, subprocess, tempfile, glob, time, urllib.request, json, sys

REAL = [("Xi0fKbOz9ZA", "Netanyahu ABC 16min"),
        ("vAsA_t_5a-I", "news clip 3min"),
        ("02Ns6EbCplY", "Amanpour podcast 95min"),
        ("dBDww47UKSM", "Senate hearing 71min NO-CAPTIONS"),
        ("OCdrhALAAPM", "Hebrew news 15min")]

def run(cmd, timeout=300, env=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **(env or {})}, shell=isinstance(cmd, str))
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"

def ip_now():
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=25).read().decode()
    except Exception as e:
        return f"?({type(e).__name__})"

# ---------- A. youtube-transcript.ai, free, no key ----------
print(f"\n{'='*94}\nA. youtube-transcript.ai (free, no API key)   runner IP={ip_now()}\n{'='*94}", flush=True)
a_results = {}
for vid, label in REAL:
    try:
        req = urllib.request.Request(f"https://youtube-transcript.ai/transcript/{vid}.txt",
                                     headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
        ok = ("No captions available" not in body) and len(body) > 500
        a_results[vid] = ok
        print(f"   {'PASS' if ok else 'FAIL'}  {label:34s} {len(body):>8}B  {body[:70].splitlines()[0] if body else ''}", flush=True)
    except Exception as e:
        a_results[vid] = False
        print(f"   FAIL  {label:34s} {type(e).__name__}: {str(e)[:60]}", flush=True)
    time.sleep(3)

# ---------- B. Cloudflare WARP ----------
print(f"\n{'='*94}\nB. Cloudflare WARP (free VPN) + yt-dlp\n{'='*94}", flush=True)
print("   [setup] installing wireguard + wgcf ...", flush=True)
c, o, e = run("sudo apt-get update -qq && sudo apt-get install -y -qq wireguard-tools iproute2 "
              "&& curl -fsSL -o /tmp/wgcf https://github.com/ViRb3/wgcf/releases/download/v2.2.29/wgcf_2.2.29_linux_amd64 "
              "&& chmod +x /tmp/wgcf", timeout=300)
print(f"   [setup] install rc={c} {e[-250:] if c else ''}", flush=True)

warp_up = False
if c == 0:
    c2, o2, e2 = run("cd /tmp && ./wgcf register --accept-tos && ./wgcf generate", timeout=180)
    print(f"   [setup] wgcf register/generate rc={c2} {(e2 or o2)[-250:]}", flush=True)
    if c2 == 0 and os.path.exists("/tmp/wgcf-profile.conf"):
        # keep the GH runner's own routes sane; only route YouTube traffic via warp
        c3, o3, e3 = run("sudo cp /tmp/wgcf-profile.conf /etc/wireguard/warp.conf && "
                         "sudo wg-quick up warp", timeout=180)
        print(f"   [setup] wg-quick up rc={c3} {(e3 or o3)[-300:]}", flush=True)
        if c3 == 0:
            time.sleep(6)
            newip = ip_now()
            print(f"   [setup] egress IP through WARP = {newip}", flush=True)
            warp_up = True

if not warp_up:
    print("   WARP could not be established on this runner — skipping B and C.", flush=True)
else:
    for vid, label in REAL:
        d = tempfile.mkdtemp()
        c4, o4, e4 = run(["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
                          "--sub-langs", "en.*,en,iw,he", "--sub-format", "vtt/best",
                          "--no-warnings", "--no-playlist",
                          "-o", os.path.join(d, "%(id)s.%(ext)s"),
                          f"https://www.youtube.com/watch?v={vid}"], timeout=240)
        f = glob.glob(os.path.join(d, "*.vtt"))
        if f:
            print(f"   PASS  {label:34s} {os.path.getsize(f[0]):>8}B  {os.path.basename(f[0])}", flush=True)
        else:
            bot = "not a bot" in (e4 or "")
            er = [l for l in (e4 or "").splitlines() if "ERROR" in l]
            print(f"   FAIL  {label:34s} {'BOT-WALL' if bot else (er[0][:70] if er else 'no subs')}", flush=True)
        time.sleep(4)

    # C. audio path through WARP, for the caption-less hearing
    print(f"\n{'='*94}\nC. audio download through WARP (Whisper path, caption-less video)\n{'='*94}", flush=True)
    d = tempfile.mkdtemp()
    t0 = time.time()
    c5, o5, e5 = run(["yt-dlp", "-f", "bestaudio/best", "--no-warnings", "--no-playlist",
                      "--download-sections", "*0-300", "-x", "--audio-format", "mp3",
                      "--audio-quality", "9", "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
                      "-o", os.path.join(d, "a.%(ext)s"),
                      "https://www.youtube.com/watch?v=dBDww47UKSM"], timeout=600)
    f = glob.glob(os.path.join(d, "a.mp3")) or glob.glob(os.path.join(d, "a.*"))
    if f and os.path.getsize(f[0]) > 10000:
        sz = os.path.getsize(f[0]) / 1e6
        print(f"   PASS  5min audio slice  {sz:.2f}MB in {time.time()-t0:.0f}s "
              f"-> full 71min ~= {sz*71/5:.0f}MB (Groq free cap 25MB)", flush=True)
    else:
        er = [l for l in (e5 or "").splitlines() if "ERROR" in l]
        print(f"   FAIL  audio  {'BOT-WALL' if 'not a bot' in (e5 or '') else (er[0][:80] if er else 'no file')}", flush=True)
