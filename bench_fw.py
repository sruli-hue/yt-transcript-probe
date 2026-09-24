import sys, time, os
from faster_whisper import WhisperModel

model_name = sys.argv[1]
compute = sys.argv[2] if len(sys.argv) > 2 else "int8"
threads = int(sys.argv[3]) if len(sys.argv) > 3 else os.cpu_count()

t0 = time.time()
m = WhisperModel(model_name, device="cpu", compute_type=compute, cpu_threads=threads)
t1 = time.time()
print(f"MODEL={model_name} COMPUTE={compute} THREADS={threads}")
print(f"LOAD_SEC={t1-t0:.1f}")

t2 = time.time()
segments, info = m.transcribe("bench.wav", beam_size=1, vad_filter=False)
segs = list(segments)
t3 = time.time()

audio_sec = 600.0
print(f"TRANSCRIBE_SEC={t3-t2:.1f}")
print(f"TOTAL_SEC={t3-t0:.1f}")
print(f"RTF={(t3-t2)/audio_sec:.3f}  (x_realtime={audio_sec/(t3-t2):.2f})")
print(f"SEGMENTS={len(segs)}  LAST_END={segs[-1].end if segs else 0:.1f}")
print(f"EXTRAPOLATED_60MIN_SEC={((t3-t2)/audio_sec)*3600:.0f}")
txt = " ".join(s.text for s in segs)
print("CHARS=", len(txt))
print("FIRST200:", txt[:200])
