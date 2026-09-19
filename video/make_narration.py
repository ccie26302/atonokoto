"""docs/VIDEO_NARRATION.md の一文ずつを Google Cloud Text-to-Speech で video/nNN.wav にする。

使い方: python3 video/make_narration.py [voice]
  voice の既定は ja-JP-Chirp3-HD-Kore。gcloud のログインとプロジェクトを使う。
"""
import json, os, re, subprocess, sys, base64, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "VIDEO_NARRATION.md")
OUT = os.path.join(ROOT, "video")
PROJECT = "forward-vector-470012-n8"
VOICE = sys.argv[1] if len(sys.argv) > 1 else "ja-JP-Chirp3-HD-Kore"

# 読み方の指定（Chirp 3 HD は SSML 非対応なので文字列で置き換える）
READ = [
    ("あとのこと", "アトノコト"),
    ("enclave", "エンクレーブ"),
    ("digest", "ダイジェスト"),
    ("iCloud+", "アイクラウドプラス"),
    ("iCloud", "アイクラウド"),
    ("Google アカウント", "グーグルアカウント"),
    ("Google Cloud", "グーグルクラウド"),
    ("Gemini", "ジェミニ"),
    ("Drive", "ドライブ"),
    ("YouTube", "ユーチューブ"),
    ("Cloud Run", "クラウドラン"),
    ("Vertex AI", "バーテックスエーアイ"),
    ("ADK", "エーディーケー"),
    ("Cloud KMS", "クラウドケーエムエス"),
    ("Confidential Space", "コンフィデンシャルスペース"),
    ("Sensitive Data Protection", "センシティブ データ プロテクション"),
    ("三十日", "さんじゅうにち"),
    ("六十日", "ろくじゅうにち"),
    ("七日", "なのか"),
    ("八十二日", "はちじゅうににち"),
    ("七十二通", "ななじゅうにつう"),
    ("403", "よんまるさん"),
    ("一万円分", "いちまんえんぶん"),
    ("拒否 1", "拒否"),
    ("拒否 2", "拒否"),
]


def lines():
    out = []
    for row in open(SRC, encoding="utf-8"):
        m = re.match(r"\|\s*(\d{2})\s*\|\s*(\d+)\s*\|[^|]*\|\s*(.+?)\s*\|\s*$", row)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def synth(tok, text, path):
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "ja-JP", "name": VOICE},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000, "speakingRate": float(os.environ.get("RATE", "1.1"))},
    }
    req = urllib.request.Request(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + tok, "x-goog-user-project": PROJECT,
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        audio = json.load(r)["audioContent"]
    open(path, "wb").write(base64.b64decode(audio))


def main():
    tok = token()
    rows = lines()
    if len(rows) != 37:
        raise SystemExit(f"台本の行数が 37 でない: {len(rows)}")
    for n, sec, text in rows:
        spoken = text
        for a, b in READ:
            spoken = spoken.replace(a, b)
        path = os.path.join(OUT, f"n{n:02d}.wav")
        synth(tok, spoken, path)
        dur = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], text=True).strip()
        print(f"n{n:02d} {sec:>4}s {float(dur):5.2f}s  {text}")


if __name__ == "__main__":
    main()
