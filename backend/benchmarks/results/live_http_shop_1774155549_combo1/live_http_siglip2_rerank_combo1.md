# Retrieval Benchmark Report

Strategy: `live_http_siglip2_rerank_combo1`
Dataset: `shop_1774155549_live_http_combo1`

## Dataset

- Products: 18
- Catalog images: 3667
- Query images: 106

## Exact Top-1

Top-1 exact matches: 93 / 106 (87.74%)

## Metrics

| Metric | Value |
| --- | --- |
| Queries | 106 |
| Hit@1 | 87.74% |
| Hit@3 | 99.06% |
| MRR@5 | 0.9347 |

## Query Groups

| Group | Queries | Hit@1 | Hit@3 | MRR@5 |
| --- | --- | --- | --- | --- |
| clean_web | 54 | 87.04% | 100.00% | 0.9352 |
| discord_noise | 52 | 88.46% | 98.08% | 0.9343 |

## Top-1 Misses

- [discord_noise] 勾n zoom阿尔法跑步鞋(多色合集) / `` -> expected `916`, predicted `922` (勾k SB板鞋(多色合集), 1.0809)
- [clean_web] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `918`, predicted `931` (勾n VapormaxFlyknit气垫鞋, 1.0197)
- [clean_web] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `918`, predicted `931` (勾n VapormaxFlyknit气垫鞋, 1.0166)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `923`, predicted `927` (勾dg 板鞋(三色合集), 1.0513)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `924`, predicted `922` (勾k SB板鞋(多色合集), 1.0229)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `924`, predicted `933` (勾1 粉色板鞋, 0.9879)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `925`, predicted `927` (勾dg 板鞋(三色合集), 0.9775)
- [clean_web] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `933` (勾1 粉色板鞋, 1.0380)
- [discord_noise] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `926`, predicted `922` (勾k SB板鞋(多色合集), 1.0229)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `927`, predicted `922` (勾k SB板鞋(多色合集), 1.0229)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `930`, predicted `927` (勾dg 板鞋(三色合集), 1.0049)
- [discord_noise] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `932`, predicted `931` (勾n VapormaxFlyknit气垫鞋, 1.0082)
- [discord_noise] 勾1 粉色板鞋 / `` -> expected `933`, predicted `925` (勾dg 联名DunkSB低帮板鞋, 1.0230)

## Dataset Failures

None.
