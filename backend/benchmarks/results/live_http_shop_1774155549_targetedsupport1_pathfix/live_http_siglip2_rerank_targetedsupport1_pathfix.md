# Retrieval Benchmark Report

Strategy: `live_http_siglip2_rerank_targetedsupport1_pathfix`
Dataset: `shop_1774155549_live_http_targetedsupport1_pathfix`

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
| clean_web | 54 | 85.19% | 100.00% | 0.9228 |
| discord_noise | 52 | 86.54% | 98.08% | 0.9279 |

## Top-1 Misses

- [clean_web] 勾n ly联名 A*ir *orce 1 Low series / `` -> expected `919`, predicted `614` (AF系列合集, 0.9982)
- [discord_noise] 勾3 aj3黑猫 / `` -> expected `920`, predicted `709` (3, 1.0022)
- [discord_noise] 勾3 aj3黑猫 / `` -> expected `920`, predicted `709` (3, 1.0124)
- [clean_web] 勾k SB板鞋(多色合集) / `` -> expected `922`, predicted `924` (勾1 UN联名板鞋, 1.0312)
- [discord_noise] 勾k SB板鞋(多色合集) / `` -> expected `922`, predicted `916` (勾n zoom阿尔法跑步鞋(多色合集), 1.0584)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `923`, predicted `927` (勾dg 板鞋(三色合集), 1.0513)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `924`, predicted `933` (勾1 粉色板鞋, 1.0079)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `925`, predicted `927` (勾dg 板鞋(三色合集), 0.9775)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `925`, predicted `933` (勾1 粉色板鞋, 1.0262)
- [clean_web] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `933` (勾1 粉色板鞋, 1.0380)
- [discord_noise] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `924` (勾1 UN联名板鞋, 1.0312)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `927`, predicted `924` (勾1 UN联名板鞋, 1.0312)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `930`, predicted `927` (勾dg 板鞋(三色合集), 1.0049)
- [clean_web] 勾n VapormaxFlyknit气垫鞋 / `` -> expected `931`, predicted `918` (勾n HotStep2气垫运动鞋(基础色合集), 1.0583)
- [discord_noise] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `932`, predicted `931` (勾n VapormaxFlyknit气垫鞋, 1.0082)

## Dataset Failures

None.
