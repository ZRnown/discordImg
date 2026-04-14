# Retrieval Benchmark Report

Strategy: `live_http_siglip2_rerank_querycluster1_pathfix`
Dataset: `shop_1774155549_live_http_querycluster1_pathfix`

## Dataset

- Products: 18
- Catalog images: 89
- Query images: 106

## Exact Top-1

Top-1 exact matches: 91 / 106 (85.85%)

## Metrics

| Metric | Value |
| --- | --- |
| Queries | 106 |
| Hit@1 | 85.85% |
| Hit@3 | 99.06% |
| MRR@5 | 0.9253 |

## Query Groups

| Group | Queries | Hit@1 | Hit@3 | MRR@5 |
| --- | --- | --- | --- | --- |
| clean_web | 54 | 87.04% | 100.00% | 0.9352 |
| discord_noise | 52 | 84.62% | 98.08% | 0.9151 |

## Top-1 Misses

- [clean_web] 勾n ly联名 A*ir *orce 1 Low series / `` -> expected `919`, predicted `614` (AF系列合集, 0.9982)
- [discord_noise] 勾3 aj3黑猫 / `` -> expected `920`, predicted `709` (3, 1.0022)
- [discord_noise] 勾3 aj3黑猫 / `` -> expected `920`, predicted `709` (3, 1.0124)
- [discord_noise] 勾k SB板鞋(多色合集) / `` -> expected `922`, predicted `916` (勾n zoom阿尔法跑步鞋(多色合集), 1.0084)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `923`, predicted `927` (勾dg 板鞋(三色合集), 1.0013)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `924`, predicted `922` (勾k SB板鞋(多色合集), 0.9929)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `925`, predicted `927` (勾dg 板鞋(三色合集), 0.9775)
- [clean_web] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `933` (勾1 粉色板鞋, 1.0380)
- [discord_noise] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `922` (勾k SB板鞋(多色合集), 0.9929)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `927`, predicted `922` (勾k SB板鞋(多色合集), 0.9929)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `930`, predicted `927` (勾dg 板鞋(三色合集), 1.0049)
- [clean_web] 勾n VapormaxFlyknit气垫鞋 / `` -> expected `931`, predicted `918` (勾n HotStep2气垫运动鞋(基础色合集), 1.0083)
- [discord_noise] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `932`, predicted `931` (勾n VapormaxFlyknit气垫鞋, 0.9582)
- [clean_web] 勾1 粉色板鞋 / `` -> expected `933`, predicted `924` (勾1 UN联名板鞋, 0.9626)
- [discord_noise] 勾1 粉色板鞋 / `` -> expected `933`, predicted `925` (勾dg 联名DunkSB低帮板鞋, 1.0230)

## Dataset Failures

None.
