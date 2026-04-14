# Live HTTP Regression Summary

Endpoint: `http://127.0.0.1:5112/search_similar`
Manifest: `/Users/wanghaixin/.config/superpowers/worktrees/discord-marketing-system/feat-accuracy-autoresearch/backend/benchmarks/data/shop_1774155549_manifest_v1_strict_image_only.json`
Scope: `["Closet"]`

Top1 exact: 94 / 106 (0.8868)
Hit@3: 0.9906
MRR@5: 0.9395

## Query Groups
- clean_web: Top1 48 / 54 (0.8889), Hit@3 1.0000, MRR@5 0.9444
- discord_noise: Top1 46 / 52 (0.8846), Hit@3 0.9808, MRR@5 0.9343

## Latency

- count: 106
- min_seconds: 0.8784
- mean_seconds: 1.5757
- median_seconds: 1.8250
- p90_seconds: 2.0155
- p95_seconds: 2.0516
- p99_seconds: 2.0660
- max_seconds: 2.0835

report_json=/Users/wanghaixin/.config/superpowers/worktrees/discord-marketing-system/feat-accuracy-autoresearch/backend/benchmarks/results/live_http_shop_1774155549_scopefix_20260325/live_http_scopefix_20260325.json
report_md=/Users/wanghaixin/.config/superpowers/worktrees/discord-marketing-system/feat-accuracy-autoresearch/backend/benchmarks/results/live_http_shop_1774155549_scopefix_20260325/live_http_summary.md
