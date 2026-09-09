#!/usr/bin/env python3
"""買い物・予約の通知メールを「本人が動いた」合図にする。

日本で使われている利用者側のサービス（Amazon、楽天、メルカリ、PayPay など）は、本人の利用履歴を第三者に読ませる
API を持たない。代わりに、注文確認や決済通知は必ずメールで来る。見張りが今読んでいる Gmail のメタデータ
（差出人・件名・受信日時。gmail.metadata スコープの範囲）だけで判定し、本文は読まない。

守ること:
  - 差出人は「表示名」ではなくアドレスのドメインで見る。表示名は誰でも名乗れる
  - 定期便・サブスクの自動更新・請求は本人が死んでも届くので、合図から外す（EXCLUDE）
  - カード会社の「ご利用のお知らせ」は、件名から単発か定期かを区別できないので数えない
  - 記録に残すのは「どの店」「いつ」「何件」だけ。件名そのものは保存しない
  - 偽装メールで作れるのは「生きているように見せる」方向だけ（発火を遅らせる）。早める方向には使えない
  - それでも第三者が正規の通知を届けられる（ゲスト予約、出品者への「購入されました」など）ので、
    この合図は「弱い源」として扱い、Google 上の本人の活動が 60 日止まれば確認者に問う（state.py の weak）。
    受動形（購入されました＝出品者側）は拾わない。サブスク更新と件名が同じ店（App Store、Google Play）は外した

classify(from_addr, subject) -> vendor 名 | None
"""
from __future__ import annotations
import re

# ドメインは末尾一致（サブドメイン込み）。「@」を含む項目はアドレス完全一致（google.com のように広すぎるドメインの店に使う）。
# 「=」で始まる項目はドメイン完全一致（銀行は取引通知と宣伝でサブドメインが違うので、宣伝側を弾く）。
# kind は 買い物 / 予約 / 決済 / チャージ / 振込
VENDORS = [
    ("Amazon",           ("amazon.co.jp", "amazon.com"),                      "買い物"),
    ("楽天市場",          ("rakuten.co.jp", "rakuten.com"),                     "買い物"),
    ("Yahoo!ショッピング", ("shopping.yahoo.co.jp", "mail.yahoo.co.jp"),        "買い物"),
    ("メルカリ",          ("mercari.jp", "mercari.com"),                        "買い物"),
    ("ヨドバシ",          ("yodobashi.com",),                                   "買い物"),
    ("ZOZOTOWN",         ("zozo.jp", "zozotown.jp"),                           "買い物"),
    ("ユニクロ",          ("uniqlo.com", "mail.uniqlo.com"),                    "買い物"),
    ("Uber Eats",        ("uber.com", "ubereats.com"),                         "買い物"),
    ("出前館",            ("demae-can.com",),                                   "買い物"),
    # App Store と Google Play は外した: サブスクの自動更新も「領収書」の同じ件名で届き、本文を読まない限り単発と区別できない
    ("マクドナルド",       ("mdj.jp",),                                          "買い物"),   # モバイルオーダー
    ("スターバックス",     ("starbucks.co.jp",),                                 "買い物"),
    ("楽天銀行",          ("ac.rakuten-bank.co.jp",),                           "振込"),     # 「支払いを行いました」「振込を受け付けました」。入金は本人の動きではないので EXCLUDE
    ("SBI新生銀行",       ("=sbishinseibank.co.jp",),                           "振込"),     # mc.sbishinseibank.co.jp は宣伝
    ("auじぶん銀行",       ("jibunbank.co.jp",),                                 "振込"),
    ("住信SBIネット銀行",  ("netbk.co.jp",),                                     "振込"),
    ("三菱UFJ銀行",       ("bk.mufg.jp",),                                      "振込"),
    ("みずほ銀行",        ("mizuhobank.co.jp",),                                "振込"),
    ("ゆうちょ銀行",       ("jp-bank.japanpost.jp",),                            "振込"),
    ("PayPay",           ("paypay.ne.jp", "paypay-corp.co.jp"),                "決済"),
    ("モバイルSuica",     ("mobilesuica.com", "jreast.co.jp"),                  "チャージ"),
    ("じゃらん",          ("jalan.net",),                                       "予約"),
    ("楽天トラベル",       ("travel.rakuten.co.jp",),                            "予約"),
    ("Booking.com",      ("booking.com",),                                     "予約"),
    ("Airbnb",           ("airbnb.com", "airbnb.jp"),                          "予約"),
    ("ANA",              ("ana.co.jp",),                                       "予約"),
    ("JAL",              ("jal.com", "jal.co.jp"),                             "予約"),
    ("えきねっと",        ("eki-net.com",),                                     "予約"),
    ("スマートEX",        ("smart-ex.jp", "expy.jp"),                           "予約"),
    ("ぐるなび",          ("gnavi.co.jp",),                                     "予約"),
    ("食べログ",          ("tabelog.com",),                                     "予約"),
    ("Steam",            ("steampowered.com",),                                "買い物"),
    ("Nintendo",         ("nintendo.net", "nintendo.co.jp", "nintendo.com"),   "買い物"),
    ("PlayStation",      ("sony.com", "playstation.com", "sonyentertainmentnetwork.com"), "買い物"),
]

# 本人が今動いた、と言える「完了した取引」の言い回しだけを拾う（単語ではなく句。「予約は今がおトク」のような宣伝を弾く）
INCLUDE = re.compile(
    r"注文ありがとう|ご注文(内容)?の(ご)?確認|ご注文を承り|注文を受け付け|注文番号|ご注文の商品|でのご注文|order confirmation|your order|order #|"
    r"発送しました|出荷しました|発送のお知らせ|出荷のお知らせ|shipped|お届け予定|"
    r"購入が完了|購入完了|購入手続き(が)?完了|お買い上げありがとう|お買上げありがとう|"
    r"領収書|レシート|receipt|"
    r"支払いを行いました|お支払いが完了|支払いが完了|支払い完了|決済が完了|決済完了|決済のお知らせ|payment (was )?(completed|received)|"
    r"振込依頼を受け付け|振込を受け付け|振込が完了|振込完了|送金が完了|送金完了|振替を受け付け|"
    r"チャージ(が)?完了|チャージしました|"
    r"ご予約(内容)?の(ご)?確認|予約が完了|予約完了|予約を承り|ご予約ありがとう|予約受付|reservation (is )?confirmed|booking confirm|itinerary|旅程|"
    r"e?チケット(を)?(発券|購入)|搭乗券|乗車券|チケットの購入",
    re.I)
# 本人が死んでも届くもの。ひとつでも当たれば拾わない
EXCLUDE = re.compile(
    r"定期|自動更新|自動継続|更新のお知らせ|更新され|renew|subscription|サブスクリプション|会費|年会費|月額|"
    r"請求|ご利用料金|ご利用明細|明細|invoice|statement|引き落とし|引落|口座振替|入金|振込入金|"
    r"キャンペーン|クーポン|セール|sale|おすすめ|オススメ|おトク|お得|限定|プレゼント|チャンス|セミナー|ご紹介|ご案内|挑戦|PR|ポイント|newsletter|メルマガ|お知らせ$|休止|注意|重要|"
    r"パスワード|password|セキュリティ|security|ログイン|sign.?in|認証|verification|確認コード|"
    r"配信停止|unsubscribe|アンケート|survey|レビューをお願い|評価をお願い",
    re.I)

def _domain(from_addr: str) -> str:
    m = re.search(r"<([^>]+)>", from_addr or "")
    addr = (m.group(1) if m else (from_addr or "")).strip().lower()
    return addr.rsplit("@", 1)[-1] if "@" in addr else ""

def _addr(from_addr: str) -> str:
    m = re.search(r"<([^>]+)>", from_addr or "")
    return (m.group(1) if m else (from_addr or "")).strip().lower()

def vendor_of(from_addr: str) -> tuple[str, str] | None:
    d = _domain(from_addr); a = _addr(from_addr)
    if not d: return None
    for name, domains, kind in VENDORS:
        for x in domains:
            if "@" in x:
                if a == x: return name, kind
            elif x.startswith("="):
                if d == x[1:]: return name, kind
            elif d == x or d.endswith("." + x):
                return name, kind
    return None

def classify(from_addr: str, subject: str) -> dict | None:
    """買い物・予約の通知なら {"vendor","kind"}、違えば None。件名は返さない。"""
    v = vendor_of(from_addr)
    if not v: return None
    s = subject or ""
    if EXCLUDE.search(s): return None
    if not INCLUDE.search(s): return None
    return {"vendor": v[0], "kind": v[1]}

if __name__ == "__main__":
    T = []
    yes = [
        ("Amazon.co.jp <auto-confirm@amazon.co.jp>", "Amazon.co.jpでのご注文 #250-1234567-1234567"),
        ("Amazon.co.jp <shipment-tracking@amazon.co.jp>", "Amazon.co.jp ご注文の商品を発送しました"),
        ("楽天市場 <order@rakuten.co.jp>", "【楽天市場】ご注文内容のご確認（自動配信メール）"),
        ("メルカリ <no-reply@mercari.jp>", "購入手続きが完了しました"),
        ("PayPay <noreply@paypay.ne.jp>", "PayPayでのお支払いが完了しました"),
        ("Uber Eats <noreply@uber.com>", "本日のご注文の領収書"),
        ("じゃらん <info@jalan.net>", "【じゃらん】ご予約内容のご確認"),
        ("モバイルSuica <mobilesuica@mobilesuica.com>", "チャージが完了しました"),
        ("マクドナルド <noreply@nsp.mdj.jp>", "【モバイルオーダー】ご注文ありがとうございます"),          # 受信箱で実測した型
        ("楽天銀行 <info@ac.rakuten-bank.co.jp>", "【楽天銀行】支払いを行いました"),                    # 同上
        ("SBI新生銀行 <info@sbishinseibank.co.jp>", "【SBI新生銀行：取引通知】振込依頼を受け付けました/ Fund Transfer Notification"),
    ]
    no = [
        ("Amazon.co.jp <no-reply@amazon.co.jp>", "定期おトク便のお届け予定"),
        ("Amazon Prime <prime@amazon.co.jp>", "Amazonプライム会費のお支払いについて"),
        ("Apple <no_reply@email.apple.com>", "サブスクリプションが更新されました"),
        ("Google Play <googleplay-noreply@google.com>", "定期購入の更新: YouTube Premium"),
        ("楽天カード <info@mail.rakuten-card.co.jp>", "カード利用のお知らせ"),                      # 店を許可していない
        ("Amazon <amazon-security@evil.example>", "Amazon.co.jpでのご注文 #250"),                 # 表示名だけ Amazon
        ("Amazon.co.jp <account-update@amazon.co.jp>", "アカウントのセキュリティに関するお知らせ"),
        ("楽天市場 <news@rakuten.co.jp>", "【楽天市場】本日限定クーポンで注文がお得"),               # クーポンは除外が勝つ
        ("メルカリ <no-reply@mercari.jp>", "メルカリからのお知らせ"),
        ("PayPay <noreply@paypay.ne.jp>", "PayPayポイントが付与されました"),
        ("メルカリ <no-reply@mercari.jp>", "商品が購入されました"),                                       # 出品者側 = 第三者の行為
        ("Apple <no_reply@email.apple.com>", "Apple からの領収書です。"),                                 # 定期課金の更新と同じ件名
        ("Google Play <googleplay-noreply@google.com>", "Google Play のご注文の領収書（注文番号 GPA.1234）"),
        ("Firebase <firebase-noreply@google.com>", "[Firebase] プロジェクト「verify」が従量課金制の Blaze のお支払いプランに"),   # google.com は店ではない
        ("楽天銀行 <info@ac.rakuten-bank.co.jp>", "【楽天銀行】入金がありました"),                          # 入金は他人の動き
        ("auじぶん銀行 <info@jibunbank.co.jp>", "【auじぶん銀行】振込入金のご連絡"),
        ("三井住友カード <info@vpass.ne.jp>", "ご利用のお知らせ【三井住友カード】"),                       # 単発か定期か分からない
        ("スマートEX <info@smart-ex.jp>", "【スマートEX】 お客様情報登録／変更完了"),
        ("スマートEX <info@expy.jp>", "【3WEEK SALE】秋旅・年末年始の予約は今がおトク！"),                  # 受信箱で実測した宣伝
        ("スマートEX <info@expy.jp>", "9月出発も直前予約でおトク！「直前割プラン」"),
        ("SBI新生銀行 <info@mc.sbishinseibank.co.jp>", "【SBI新生銀行】9年9月の振込サービス休止のお知らせ"),
        ("SBI新生銀行 <info@mc.sbishinseibank.co.jp>", "【新サービス】お子さまへの仕送りに。定額自動振込サービス開始"),
        ("auじぶん銀行 <info@jibunbank.co.jp>", "【9月版】ご自宅の購入をお考えの方、必見！auじぶん銀行の住宅ローンをご紹介"),
        ("auじぶん銀行 <info@jibunbank.co.jp>", "【注意】「口座の売買・レンタル等」や「送金バイト」は犯罪です。絶対に行わないでください。"),
        ("auじぶん銀行 <info@jibunbank.co.jp>", "【はじめての株式】株式取引に挑戦してみませんか？"),
        ("Nintendo <info@ccg.nintendo.com>", "【9月のお知らせ】最新ニュース、ゲームソフト、グッズ、アプリ情報などをまとめてお届けします"),
    ]
    for f, s in yes: T.append((f"拾う: {s[:28]}", classify(f, s) is not None))
    for f, s in no: T.append((f"拾わない: {s[:28]}", classify(f, s) is None))
    T.append(("店の名前が返る", classify(yes[0][0], yes[0][1]) == {"vendor": "Amazon", "kind": "買い物"}))
    ok = sum(1 for _, r in T if r)
    for n, r in T: print(("ok " if r else "NG ") + n)
    print(f"{ok}/{len(T)}")
    raise SystemExit(0 if ok == len(T) else 1)
