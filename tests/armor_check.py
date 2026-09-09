#!/usr/bin/env python3
"""受信箱の全メール本文を Model Armor (sanitizeUserPrompt) に通し、種類別に検知率を出す。
注入メール(kind=injection)が引っかかるか、良性メール(領収・登録・宣伝)が誤検知されるかの両側を測る。"""
import json, sys, os, subprocess, urllib.request, collections
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "forward-vector-470012-n8")
LOC = os.environ.get("MA_LOCATION", "us-central1")
TEMPLATE = os.environ.get("MA_TEMPLATE", "airlock")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "data")
tok = subprocess.check_output(["gcloud", "auth", "application-default", "print-access-token"]).decode().strip()
URL = f"https://modelarmor.{LOC}.rep.googleapis.com/v1/projects/{PROJECT}/locations/{LOC}/templates/{TEMPLATE}:sanitizeUserPrompt"

def sanitize(text):
    req = urllib.request.Request(URL, data=json.dumps({"userPromptData": {"text": text}}).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req))["sanitizationResult"]
    filt = r.get("filterResults", {})
    hits = []
    for k, v in filt.items():
        inner = next(iter(v.values())) if isinstance(v, dict) and v else {}
        if isinstance(inner, dict) and inner.get("matchState") == "MATCH_FOUND":
            hits.append(f"{k}:{inner.get('confidenceLevel','')}")
    return r.get("filterMatchState"), hits

mails = json.load(open(os.path.join(DATA, sys.argv[2] if len(sys.argv) > 2 else "inbox.json")))
by = collections.defaultdict(lambda: [0, 0]); detail = []
for m in mails:
    state, hits = sanitize(f"件名: {m['subject']}\n差出人: {m['from']}\n\n{m['body']}")
    by[m["kind"]][1] += 1
    if state == "MATCH_FOUND":
        by[m["kind"]][0] += 1; detail.append((m["kind"], m["id"], m["subject"][:40], hits))
print(f"template {LOC}/{TEMPLATE}")
for k, (hit, n) in sorted(by.items()): print(f"  {k:12s} 検知 {hit}/{n}")
for d in detail: print("   ", d)
