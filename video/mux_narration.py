"""video/nNN.wav を atonokoto_demo_cut.mp4 に載せて atonokoto_demo.mp4 を作る。

PLAN は「編集後の動画 atonokoto_demo_cut.mp4 で、その文の画面が出る秒」。
- CUTS の区間（「通しています」の待ち時間）は落とす。
- 前の文が終わらないうちに次の場面が来るところは、場面が切り替わる直前のフレームを静止で延ばして待つ。
- 最後は入口の画面を、ナレーションが終わるまで延ばす。
"""
import os, subprocess, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(ROOT, "video")
SRC = os.path.join(V, "atonokoto_demo_cut.mp4")
OUT = os.path.join(V, "atonokoto_demo.mp4")
GAP = 0.35        # 文と文の間
TOL = 0.8         # この秒数までの遅れは静止を入れずに許す
TAIL = 1.5        # 最後の文の後に残す入口の画面

CUTS = [(96.5, 105.0)]   # 落とす区間（元の編集後動画の秒）
PLAN = [0, 3, 7, 12, 16, 20, 25, 29, 39, 43, 45, 55, 60, 75, 78, 81, 84, 86, 89, 93,
        108, 112, 117, 121, 125, 129, 138, 144, 145.5, 147, 153, 162, 167, 171, 176, 182, 185]


def dur(p):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], text=True))


def after_cuts(t):
    return t - sum(min(b, t) - a for a, b in CUTS if t > a)


vlen = dur(SRC)
holds = {}          # 元動画の秒 -> 静止の長さ
starts = []         # (n, 完成動画での開始秒, 長さ)
shift = 0.0
t_audio = 0.0
for i, plan in enumerate(PLAN):
    n = i + 1
    d = dur(os.path.join(V, f"n{n:02d}.wav"))
    scene = after_cuts(plan) + shift
    start = max(scene, t_audio)
    if start - scene > TOL:
        h = start - scene
        holds[plan] = holds.get(plan, 0) + h
        shift += h
    starts.append((n, start, d))
    t_audio = start + d + GAP

end_needed = t_audio - GAP + TAIL
new_len = after_cuts(vlen) + shift
if end_needed > new_len:
    holds[vlen] = end_needed - new_len
    new_len = end_needed

# 映像: 残す区間を、静止点で分けてつなぐ
keep = []
prev = 0.0
for a, b in CUTS:
    keep.append((prev, a)); prev = b
keep.append((prev, vlen))
pieces = []   # (start, end, hold_after)
for a, b in keep:
    pts = sorted(p for p in holds if a < p <= b)
    s = a
    for p in pts:
        pieces.append((s, p, holds[p])); s = p
    if s < b:
        pieces.append((s, b, 0.0))
fc = []
labels = []
for i, (a, b, h) in enumerate(pieces):
    f = f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS"
    if h > 0:
        f += f",tpad=stop_mode=clone:stop_duration={h:.3f}"
    fc.append(f + f"[v{i}]"); labels.append(f"[v{i}]")
fc.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")

inputs = ["-i", SRC]
amix = []
for k, (n, start, d) in enumerate(starts):
    inputs += ["-i", os.path.join(V, f"n{n:02d}.wav")]
    ms = int(start * 1000)
    fc.append(f"[{k+1}:a]adelay={ms}|{ms}[a{k}]"); amix.append(f"[a{k}]")
fc.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0,apad,atrim=end={new_len:.3f}[aout]")

cmd = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error"] + inputs + [
    "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)

print(f"元 {vlen:.1f}s → 完成 {new_len:.1f}s、落とした {sum(b-a for a,b in CUTS):.1f}s、静止 {len(holds)} 箇所（合計 {sum(holds.values()):.1f}s）")
for p in sorted(holds):
    print(f"  静止 元{p:6.1f}s に {holds[p]:4.1f}s")
for n, start, d in starts:
    print(f"n{n:02d} {start:6.1f}s – {start+d:6.1f}s")
json.dump({"holds": holds, "starts": starts, "length": new_len}, open(os.path.join(V, "timeline.json"), "w"), indent=1)

# 台本の「開始（秒）」を完成動画の秒に書き換える
doc = os.path.join(ROOT, "docs", "VIDEO_NARRATION.md")
txt = open(doc, encoding="utf-8").read()
for n, start, d in starts:
    txt = re.sub(rf"(\|\s*{n:02d}\s*\|\s*)[\d.]+(\s*\|)", rf"\g<1>{start:.1f}\g<2>", txt, count=1)
open(doc, "w", encoding="utf-8").write(txt)
