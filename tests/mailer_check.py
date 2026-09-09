#!/usr/bin/env python3
"""送信の試験。ローカルの SMTP スタブに対して、宛先制限・秘密検査・形式・日次上限・実送信を確かめる。THREAT_MODEL の「5 ケース 5/5」の実体。
SDP はローカルでは ATONOKOTO_SDP=0 で外す（本番では有効）。"""
import os, sys, asyncio, threading, tempfile, json
os.environ["ATONOKOTO_SDP"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "agents", "watch"))
tmp = tempfile.mkdtemp(); received = os.path.join(tmp, "received.txt")
os.environ["ATONOKOTO_MAIL_LEDGER"] = os.path.join(tmp, "ledger.jsonl")
os.environ["ATONOKOTO_SMTP_JSON"] = json.dumps({"host": "127.0.0.1", "port": 8026, "from": "noreply@atonokoto.example", "starttls": False})
import mailer

async def handle(r, w):
    w.write(b"220 stub\r\n"); await w.drain(); data = b""; in_data = False
    while True:
        line = await r.readline()
        if not line: break
        if in_data:
            if line.strip() == b".": in_data = False; open(received, "ab").write(data); w.write(b"250 ok\r\n"); data = b""
            else: data += line
        else:
            cmd = line.split(b" ")[0].strip().upper()
            if cmd in (b"EHLO", b"HELO"): w.write(b"250-stub\r\n250 8BITMIME\r\n")
            elif cmd == b"DATA": in_data = True; w.write(b"354 go\r\n")
            elif cmd == b"QUIT": w.write(b"221 bye\r\n"); await w.drain(); break
            else: w.write(b"250 ok\r\n")
        await w.drain()
    w.close()
async def serve(stop):
    srv = await asyncio.start_server(handle, "127.0.0.1", 8026)
    async with srv:
        while not stop.is_set(): await asyncio.sleep(0.1)
stop = threading.Event(); th = threading.Thread(target=lambda: asyncio.run(serve(stop)), daemon=True); th.start()
import time; time.sleep(0.5)
R = []
r = mailer.send("hanako@example.com", "あとのこと: 試験", "本文です。", {"hanako@example.com"}, "test"); R.append(("登録済みの宛先に送れる", r["sent"]))
r = mailer.send("attacker@evil.example", "x", "本文", {"hanako@example.com"}, "test"); R.append(("登録外の宛先は拒否", not r["sent"] and "登録" in r["reason"]))
r = mailer.send("hanako@example.com", "x", "パスワード: hunter2", {"hanako@example.com"}, "test"); R.append(("秘密が混ざった本文は拒否", not r["sent"] and "秘密" in r["reason"]))
r = mailer.send("not-an-email", "x", "本文", {"not-an-email"}, "test"); R.append(("宛先の形式を検査", not r["sent"]))
mailer.DAILY_LIMIT = 1
r = mailer.send("hanako@example.com", "x", "本文", {"hanako@example.com"}, "test"); R.append(("1 日の上限で止まる", not r["sent"] and "上限" in (r.get("reason") or "")))
raw = open(received, "rb").read().decode("utf-8", "ignore") if os.path.exists(received) else ""
R.append(("スタブが実際に受信した（Auto-Submitted 付き）", "Auto-Submitted: auto-generated" in raw and "hanako@example.com" in raw))
led = [json.loads(l) for l in open(os.environ["ATONOKOTO_MAIL_LEDGER"])]
R.append(("台帳には宛先がハッシュでしか残らない", all("@" not in json.dumps(x) for x in led)))
stop.set()
for name, ok in R: print(f"  {'OK ' if ok else 'NG '} {name}")
print(f"{sum(o for _,o in R)}/{len(R)}"); sys.exit(0 if all(o for _,o in R) else 1)
