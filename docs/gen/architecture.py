"""アーキテクチャ図の生成。Google Cloud のアイコン(diagrams パッケージ同梱)を埋め込んだ SVG を書き、headless Chrome で PNG にする。
線は箱や文字の上を通らないよう、群の間の「通路」だけを使う。"""
import base64, pathlib, sys
ICONS = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent / "icons"
OUT = pathlib.Path(__file__).resolve().parents[1]
W, H = 2000, 1260
F = "Hiragino Sans, Noto Sans JP, Helvetica Neue, Arial, sans-serif"
INK, SUB, LINE, FRAME, BLUE, RED = "#202124", "#5f6368", "#80868b", "#dadce0", "#1a73e8", "#d93025"
out = []
def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def b64(rel): return "data:image/png;base64," + base64.b64encode((ICONS / rel).read_bytes()).decode()
def t(x, y, s, size=13, fill=INK, anchor="start", bold=False):
    fw = ' font-weight="600"' if bold else ''
    out.append(f'<text x="{x}" y="{y}" font-family="{F}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{fw}>{esc(s)}</text>')
def lines(x, y, ls, size=11.5, fill=SUB, lh=17, anchor="start"):
    for i, s in enumerate(ls): t(x, y + i * lh, s, size, fill, anchor)
def icon(x, y, rel, iw): out.append(f'<image href="{b64(rel)}" x="{x-iw/2}" y="{y-iw/2}" width="{iw}" height="{iw}"/>')
def node(x, y, rel, name, notes, iw=56, side=False):
    """アイコン中心 (x,y)。side=True は名前と注記をアイコンの右に置く(上下から線を出し入れするため)。"""
    if rel: icon(x, y, rel, iw)
    if side:
        t(x + iw/2 + 12, y + 4, name, 13, INK, bold=True)
        lines(x + iw/2 + 12, y + 22, notes, 11.5, SUB, 16)
    else:
        t(x, y + iw/2 + 18, name, 13, INK, anchor="middle", bold=True)
        lines(x, y + iw/2 + 36, notes, 11.5, SUB, 16, anchor="middle")
def shield(x, y, name, notes, iw=56):
    s = iw / 56
    out.append(f'<g transform="translate({x-iw/2},{y-iw/2}) scale({s})"><path d="M28 3 L50 12 V28 C50 42 39 51 28 55 C17 51 6 42 6 28 V12 Z" fill="#e8f0fe" stroke="{BLUE}" stroke-width="2"/><path d="M19 28 L26 35 L38 21" fill="none" stroke="{BLUE}" stroke-width="3" stroke-linecap="round"/></g>')
    node(x, y, None, name, notes, iw)
def group(x, y, w, h, title, stroke=FRAME, fill="#ffffff", dash=False, tcolor=SUB):
    d = ' stroke-dasharray="8,6"' if dash else ''
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{d}/>')
    if title: t(x + 14, y + 22, title, 13, tcolor, bold=True)
def badge(x, y, n):
    out.append(f'<circle cx="{x}" cy="{y}" r="11" fill="{BLUE}"/>'); t(x, y + 4.5, str(n), 12, "#fff", "middle", True)
def edge(pts, n=None, dash=False, label=None, lpos=None, both=False, lanchor="start", lat=None):
    d = ' stroke-dasharray="7,5"' if dash else ''
    ms = ' marker-start="url(#as)"' if both else ''
    out.append(f'<path d="M{" L".join(f"{x},{y}" for x, y in pts)}" fill="none" stroke="{LINE}" stroke-width="1.8"{d} marker-end="url(#ae)"{ms}/>')
    if n is not None: badge(*lpos, n)
    if label:
        lx, ly = lat if lat else (lpos[0] + (16 if lanchor == "start" else -16), lpos[1] + 4)
        t(lx, ly, label, 11.5, SUB, lanchor)
def pill(x, y, s, w):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="26" rx="13" fill="#f1f3f4" stroke="{FRAME}"/>'); t(x + w/2, y + 17, s, 11.5, INK, "middle")

out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
out.append(f'<defs><marker id="ae" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="{LINE}"/></marker>'
           f'<marker id="as" markerWidth="9" markerHeight="9" refX="1" refY="4.5" orient="auto"><path d="M9,0 L0,4.5 L9,9 z" fill="{LINE}"/></marker></defs>')
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
t(40, 46, "あとのこと ― アーキテクチャ", 26, INK, bold=True)
t(40, 72, "デジタル遺産の執行エージェント。LLM は説明・解釈・文面のみ。判断の床とゲートは決定的。封印の復号は attestation を通った実行イメージ 1 つだけに許可。", 13, SUB)

# ---------- 左列: Google Cloud の外 ----------
group(40, 100, 320, 200, "Google（外部 API）")
pill(60, 140, "Gmail API", 140); pill(210, 140, "Drive / YouTube", 130)
pill(60, 180, "Calendar API", 140); pill(210, 180, "OAuth 2.0", 130)
lines(60, 232, ["スコープは読み取りのみ（Testing、本番は検証+CASA）", "見張るのは日時だけ（既読・送信・買い物・Drive・予定・YouTube）", "棚卸しは本文を 1 回。読み終えたら revoke"], 11.5, SUB, 17)
group(40, 320, 320, 490, "利用者")
node(110, 400, "onprem/client/user.png", "本人（ブラウザ）", ["gmail.com で Google ログイン", "同意・遺志・プラン", "封印は WebCrypto で暗号化"], 52)
pill(60, 500, "審査用アカウント（ID/PW、Google ログイン不要）", 280)
node(110, 590, "onprem/client/users.png", "確認者（2 人以上）", ["HMAC 署名リンクの二択", "「本人と連絡が取れますか」"], 52)
node(110, 720, "onprem/client/client.png", "遺族・渡す相手", ["ご報告（SDP で伏せ字）"], 52)
group(40, 830, 320, 400, "流れ（番号は図中の丸）")
lines(56, 866, ["1  Google ログイン、同意、遺志、封印（HTTPS）", "2  棚卸し: Gmail 本文を 1 回だけ読む", "3  Model Armor → Gemini（ADK 4 段）",
                "4  トークン・暗号文は Secret Manager へ", "5  06:30 JST にジョブ起動", "6  見張り: 日時メタデータだけ取得",
                "7  Gemini は説明と延長提案のみ", "8  確認者へ署名リンク → 二択で回答", "9  発火 → 最後の通知 → 7 日 → enclave 起動",
                "10 proof と判定を追記専用の監査へ", "11 遺族へご報告（SDP で伏せ字）"], 11.5, INK, 17)
out.append(f'<line x1="60" y1="1085" x2="110" y2="1085" stroke="{LINE}" stroke-width="1.8"/>'); t(120, 1089, "データ・制御", 11.5, SUB)
out.append(f'<line x1="200" y1="1085" x2="250" y2="1085" stroke="{LINE}" stroke-width="1.8" stroke-dasharray="7,5"/>'); t(260, 1089, "秘密・暗号文", 11.5, SUB)
out.append(f'<rect x="60" y="1105" width="50" height="14" fill="none" stroke="{RED}" stroke-dasharray="8,6"/>'); t(120, 1116, "信頼境界（attestation を通った TEE）", 11.5, SUB)
lines(60, 1150, ["実測値は THREAT_MODEL.md の証拠欄と一致。", "アイコン: Google Cloud architecture icons。"], 11, "#9aa0a6", 16)

# ---------- プロジェクト枠 ----------
group(400, 100, 1560, 1130, "", "#c4c7c5", "#f8f9fa")
icon(427, 123, "gcp/gcp.png", 26)
t(448, 129, "Google Cloud プロジェクト  forward-vector-470012-n8   asia-northeast1（Vertex AI Gemini は global エンドポイント）", 13, INK, bold=True)

# 1 段目
group(420, 150, 580, 330, "アプリ実行（Cloud Run、非 root、max-instances=1）")
node(560, 240, "gcp/compute/run.png", "Cloud Run サービス atonokoto-web", ["Web / API、ADK SequentialAgent（棚卸し 4 段）", "静的配信は許可リスト、CSP nonce、署名 Cookie", "レート制限・日次上限、デモは SSE で実況"])
node(800, 240, "gcp/devtools/scheduler.png", "Cloud Scheduler", ["毎日 06:30 JST", "起動権限はジョブ 1 つ"], 48, side=True)
node(800, 410, "gcp/compute/run.png", "Cloud Run ジョブ", ["atonokoto-watch（全利用者）", "床つき状態機械（LLM 不在）", "発火・最後の通知・7 日ブレーキ"], 48, side=True)
group(1020, 150, 480, 330, "AI と検査")
node(1110, 240, "gcp/ml/vertex-ai.png", "Vertex AI Gemini", ["gemini-3.5-flash / global", "predict のみのカスタムロール", "棚卸し・解釈・説明・文面"])
shield(1280, 240, "Model Armor", ["受信箱の入口で注入検知", "検知は報告のみ、従わない"])
shield(1420, 240, "Sensitive Data Protection", ["ご報告の伏せ字", "送信前の本文検査"])
lines(1040, 445, ["注入 10 変種 × N=2 で追従 0/20  判断 21/21  ゲート 16/16  状態機械 29/29  承認 8/8"], 11.5, SUB)
group(1530, 150, 400, 330, "秘密と鍵")
node(1620, 240, "gcp/security/secret-manager.png", "Secret Manager", ["利用者ごとのトークン", "封印の暗号文（sealed-*）", "署名鍵、審査用アカウント"])
node(1820, 240, "gcp/security/key-management-service.png", "Cloud KMS", ["atonokoto/seal（RSA-OAEP）", "復号 IAM は WIP 経由の", "image_digest 1 つだけ"])
lines(1550, 428, ["平文の秘密はコンテナに置かない（起動時に /tmp へ実体化）", "封印は公開鍵でブラウザが暗号化、サーバーは暗号文のみ"], 11.5, SUB)

# 2 段目
group(420, 520, 580, 280, "データと監査")
node(560, 600, "gcp/storage/storage.png", "Cloud Storage（データ）", ["atonokoto-data-*", "gcsfuse で /app/data にマウント", "data/users/<sha256(mail)[:16]>/"])
node(745, 600, "gcp/storage/storage.png", "Cloud Storage（監査）", ["atonokoto-audit-files-*", "objectCreator のみ", "保持 400 日、ハッシュ鎖"])
node(935, 600, "gcp/operations/logging.png", "Cloud Logging", ["_audit → 400 日", "KMS / Secret の", "DATA_READ 監査"], 48)
group(1020, 520, 910, 280, "IAM・供給網・コスト")
node(1090, 600, "gcp/security/iam.png", "IAM", ["カスタムロール 3", "atonokotoVertexPredict", "atonokotoUserSecrets", "atonokotoEnclaveLauncher"], 48)
node(1260, 600, "gcp/security/iam.png", "サービスアカウント", ["run-sa: Web / ジョブ", "cs-workload: enclave", "互いに他方の権限なし"], 48)
node(1430, 600, "gcp/devtools/container-registry.png", "Artifact Registry", ["web / enclave の 2 イメージ", "脆弱性スキャン有効", "digest を infra/ に固定"], 48)
node(1680, 600, "gcp/management/billing.png", "Billing", ["予算 3,000 円/月でアラート", "enclave は 30 分に 1 回", "VM は毎回削除"], 48)
node(1840, 600, "gcp/devtools/build.png", "Cloud Build", ["deploy.sh から", "イメージ 2 種"], 44)

# 3 段目: enclave
group(420, 840, 1510, 370, "執行 enclave（Confidential Space）― 信頼境界。封印はここでしか開かない", RED, "#fff", True, RED)
node(560, 930, "gcp/compute/compute-engine.png", "Confidential VM（使い捨て）", ["enc-<uid6>-<5 桁>、AMD SEV", "Confidential Space イメージ", "SA cs-workload、終わったら削除"])
node(820, 930, "gcp/security/iam.png", "Workload Identity Pool", ["cs-pool / cs-provider", "attestation → STS 交換", "条件: swname=CONFIDENTIAL_SPACE", "かつ image_digest == 承認値"], 48)
node(1080, 930, "gcp/security/key-management-service.png", "KMS 復号", ["承認済み digest → 開く（proof 一致）", "承認外 digest → 403", "Cloud Run SA → PERMISSION_DENIED"], 48)
out.append(f'<rect x="1230" y="890" width="260" height="90" rx="6" fill="#fce8e6" stroke="{RED}"/>')
t(1360, 916, "enclave 内のメモリだけ", 13, INK, "middle", True)
lines(1244, 940, ["復号した資格情報は外に出ない", "ゲート → 文面（Gemini）→ ご報告（SDP）"], 11.5, SUB, 17)
node(1660, 930, "gcp/operations/logging.png", "監査への書き込み", ["proof = SHA-256 のみ", "追記専用バケット + Logging"], 48)
edge([(590, 930), (786, 930)], label="attestation token", lpos=(600, 914))
edge([(846, 930), (1046, 930)], label="STS → 短命トークン", lpos=(860, 914))
edge([(1106, 930), (1230, 930)], label="復号", lpos=(1140, 914))
edge([(1490, 930), (1630, 930)])
lines(440, 1160, ["両側で実測: 承認済み digest の enclave は封印を開け、proof が手元の SHA-256 と一致。承認外 digest（一つ前のイメージ）は KMS が 403。Cloud Run の SA は PERMISSION_DENIED。",
                  "起動権限は atonokotoEnclaveLauncher（compute.instances.create / delete など最小）。VM 名が短いのは STS の subject 127 バイト制限のため。"], 11.5, SUB, 18)

# ---------- フロー（通路だけを通す） ----------
edge([(360, 150), (390, 150), (390, 222), (532, 222)], 2, lpos=(470, 222))                 # Gmail 本文 → web
edge([(360, 190), (375, 190), (375, 404), (776, 404)], 6, lpos=(650, 404))                 # 日時メタデータ → job
edge([(150, 400), (405, 400), (405, 240), (532, 240)], 1, lpos=(280, 400))                 # 本人 → web
edge([(776, 416), (385, 416), (385, 580), (150, 580)], 8, lpos=(385, 500))                 # job → 確認者（署名リンク）
edge([(150, 600), (395, 600), (395, 258), (532, 258)], label="二択の回答", lpos=(230, 600)) # 確認者 → web
edge([(560, 212), (560, 198), (1110, 198), (1110, 212)], 3, lpos=(900, 198))              # web → Gemini
edge([(580, 212), (580, 186), (1620, 186), (1620, 212)], 4, dash=True, lpos=(1560, 186))   # web → Secret Manager
edge([(824, 386), (1004, 386), (1004, 186)], dash=True)                                    # job → Secret Manager（合流）
edge([(824, 398), (1012, 398), (1012, 248), (1082, 248)], 7, lpos=(1012, 330))             # job → Gemini（説明）
edge([(800, 264), (800, 386)], 5, lpos=(800, 325), label="Jobs API で起動")                 # Scheduler → job
edge([(560, 268), (560, 572)], both=True, label="gcsfuse", lpos=(560, 500), lat=(572, 504))                # web ⇄ データ
edge([(800, 434), (800, 815), (560, 815), (560, 902)], 9, lpos=(700, 815), label="承認済み digest のイメージで起動、暗号文はメタデータで渡す", lat=(716, 806))  # job → VM
edge([(1660, 902), (1660, 828), (840, 828), (840, 600), (773, 600)], 10, lpos=(1200, 828)) # enclave → 監査バケット
edge([(1080, 902), (1080, 822), (1950, 822), (1950, 240), (1848, 240)], dash=True, label="復号要求（attestation を通った SA）", lpos=(1520, 822), lat=(1536, 813))  # → KMS
edge([(1360, 980), (1360, 1130), (390, 1130), (390, 720), (136, 720)], 11, lpos=(700, 1130))  # ご報告 → 遺族
out.append('</svg>')
(OUT / "architecture.svg").write_text("\n".join(out)); print("svg written")
