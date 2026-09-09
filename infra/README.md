# 裏で回す

見張りは常駐しない。1 日 1 回だけ起きて、読み取りだけして、終わる。

## Mac（開発中）
launchd で毎朝 6:30 に `agents/watch/run.py` を実行する。

```bash
cp infra/com.atonokoto.watch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.atonokoto.watch.plist
launchctl start com.atonokoto.watch        # いますぐ 1 回
```
止める: `launchctl unload ~/Library/LaunchAgents/com.atonokoto.watch.plist`

## 本番（Cloud Run + Cloud Scheduler）
同じ `run.py` を Cloud Run ジョブにし、Cloud Scheduler が 1 日 1 回叩く。トークンは Secret Manager、状態は GCS バケット（JSON）。監査は Cloud Logging と追記専用バケット。
