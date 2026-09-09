#!/usr/bin/env python3
"""index.html / confirm.html の innerHTML 代入に入る ${…} を全部列挙し、esc(…) か数値化（+x）か定数でないものを挙げる。
外部由来の文字列がエスケープ無しで HTML に入る経路を機械で見つけるための粗い検査。"""
import re, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
SAFE_PREFIX = ("esc(", "+", "WNAME[", "NAME[", "NAMES[", "SIGTXT[", "LOGIN[", "VIA[", "st.k", "WILL[", "a.will===", "a.cost===", "a.plan===", "has(", "i}", "w}")
bad = 0
for fn in ("web/index.html", "web/confirm.html"):
    src = open(os.path.join(HERE, "..", fn), encoding="utf-8").read()
    # innerHTML = `...` / innerHTML += `...` / .map(... => `...`) の中のテンプレートを対象にする
    for m in re.finditer(r"innerHTML\s*\+?=\s*(.+?);\n", src, re.S):
        block = m.group(1)
        exprs = [e.strip() for e in re.findall(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", block)]
        # 条件つきの塊 ${cond ? `...` : ""} は中のテンプレートを同じ規則で見る（塊ごと安全扱いにしない）
        i = 0
        while i < len(exprs):
            e = exprs[i]; i += 1
            m2 = re.fullmatch(r"\(.*?\)\s*\?\s*`(.*)`\s*:\s*(\"\"|''|``)", e, re.S)
            if m2:
                exprs += [x.strip() for x in re.findall(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", m2.group(1))]; continue
            # `X[k]||k` の形は右辺が素の値なので安全扱いにしない（esc(k) を要求する）
            if e.startswith(SAFE_PREFIX) and not re.search(r"\|\|\s*[a-z]\.[a-z]+$", e): continue
            # 数値・真偽・三項の定数文字列は安全
            if re.fullmatch(r"[\w.]+\s*(===|!==|\?|>|<)[^`]*", e) and "esc(" not in e and "a.n" not in e and ".name" not in e and "to" not in e:
                continue
            # 文字列を作る三項で外部文字列が混ざるもの
            if any(k in e for k in ("a.n", ".name", "a.to", "d.to", "p.to", "e.message", "j.", "t.event", "w.name", "w.mail", "explanation", "signote", "sigid", "r.note", "ctx.")) and "esc(" not in e:
                print(f"  NG {fn}: ${{{e[:90]}}}"); bad += 1
print("問題なし" if not bad else f"{bad} 件")
sys.exit(1 if bad else 0)
