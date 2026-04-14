# Retrieval Benchmark Report

Strategy: `siglip2_rerank`
Dataset: `shop-1774155549-v1`

## Dataset

- Products: 18
- Catalog images: 89
- Query images: 106

## Exact Top-1

Top-1 exact matches: 45 / 106 (42.45%)

## Metrics

| Metric | Value |
| --- | --- |
| Queries | 106 |
| Hit@1 | 42.45% |
| Hit@3 | 59.43% |
| MRR@5 | 0.5052 |

## Query Groups

| Group | Queries | Hit@1 | Hit@3 | MRR@5 |
| --- | --- | --- | --- | --- |
| clean_web | 54 | 50.00% | 62.96% | 0.5614 |
| discord_noise | 52 | 34.62% | 55.77% | 0.4468 |

## Top-1 Misses

- [clean_web] 勾n zoom阿尔法跑步鞋(多色合集) / `` -> expected `7713998250`, predicted `7713967542` (勾n Max90气垫运动鞋(多色合集), 0.6171)
- [discord_noise] 勾n zoom阿尔法跑步鞋(多色合集) / `` -> expected `7713998250`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.6865)
- [discord_noise] 勾n zoom阿尔法跑步鞋(多色合集) / `` -> expected `7713998250`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.6918)
- [clean_web] 勾1 JOR*AN 1 D*I*O*R联名 / `` -> expected `7716766172`, predicted `7714044088` (勾1 UN联名板鞋, 0.8688)
- [discord_noise] 勾1 JOR*AN 1 D*I*O*R联名 / `` -> expected `7716766172`, predicted `7713998068` (勾dg 板鞋(多色/品牌联名合集), 0.8938)
- [discord_noise] 勾1 JOR*AN 1 D*I*O*R联名 / `` -> expected `7716766172`, predicted `7714044088` (勾1 UN联名板鞋, 0.7323)
- [clean_web] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.7445)
- [clean_web] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7711058275` (勾n shoxRide2运动鞋(四色合集), 0.7061)
- [clean_web] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.8295)
- [discord_noise] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7713967542` (勾n Max90气垫运动鞋(多色合集), 0.7019)
- [discord_noise] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7711058275` (勾n shoxRide2运动鞋(四色合集), 0.7656)
- [discord_noise] 勾n HotStep2气垫运动鞋(基础色合集) / `` -> expected `7713967326`, predicted `7711058275` (勾n shoxRide2运动鞋(四色合集), 0.7554)
- [clean_web] 勾n ly联名 A*ir *orce 1 Low series / `` -> expected `7713673587`, predicted `7711016729` (勾af 联名OFF休闲防滑板鞋(多色合集), 0.8752)
- [discord_noise] 勾n ly联名 A*ir *orce 1 Low series / `` -> expected `7713673587`, predicted `7714063684` (勾1 粉色板鞋, 0.7580)
- [discord_noise] 勾3 aj3黑猫 / `` -> expected `7712698523`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.8422)
- [clean_web] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713998250` (勾n zoom阿尔法跑步鞋(多色合集), 0.7096)
- [clean_web] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713967326` (勾n HotStep2气垫运动鞋(基础色合集), 0.6529)
- [clean_web] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713967326` (勾n HotStep2气垫运动鞋(基础色合集), 0.6905)
- [discord_noise] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713967326` (勾n HotStep2气垫运动鞋(基础色合集), 0.6632)
- [discord_noise] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713998250` (勾n zoom阿尔法跑步鞋(多色合集), 0.6884)
- [discord_noise] 勾n HotStepTerra运动跑步鞋 / `` -> expected `7714063870`, predicted `7713998250` (勾n zoom阿尔法跑步鞋(多色合集), 0.7548)
- [clean_web] 勾k SB板鞋(多色合集) / `` -> expected `7713996934`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.8315)
- [clean_web] 勾k SB板鞋(多色合集) / `` -> expected `7713996934`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.7069)
- [discord_noise] 勾k SB板鞋(多色合集) / `` -> expected `7713996934`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.6918)
- [discord_noise] 勾k SB板鞋(多色合集) / `` -> expected `7713996934`, predicted `7714044088` (勾1 UN联名板鞋, 0.7859)
- [clean_web] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `7711058275`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.7561)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `7711058275`, predicted `7713967326` (勾n HotStep2气垫运动鞋(基础色合集), 0.6998)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `7711058275`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.6780)
- [discord_noise] 勾n shoxRide2运动鞋(四色合集) / `` -> expected `7711058275`, predicted `7710979345` (勾dg 板鞋(三色合集), 0.6899)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `7714044088`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.8315)
- [clean_web] 勾1 UN联名板鞋 / `` -> expected `7714044088`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7938)
- [discord_noise] 勾1 UN联名板鞋 / `` -> expected `7714044088`, predicted `7713967542` (勾n Max90气垫运动鞋(多色合集), 0.6799)
- [discord_noise] 勾1 UN联名板鞋 / `` -> expected `7714044088`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.7055)
- [discord_noise] 勾1 UN联名板鞋 / `` -> expected `7714044088`, predicted `7713998068` (勾dg 板鞋(多色/品牌联名合集), 0.6646)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `7714032296`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7109)
- [clean_web] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `7714032296`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7883)
- [discord_noise] 勾dg 联名DunkSB低帮板鞋 / `` -> expected `7714032296`, predicted `7713673587` (勾n ly联名 A*ir *orce 1 Low series, 0.5947)
- [clean_web] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `7711016729`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7255)
- [clean_web] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `7711016729`, predicted `7714063684` (勾1 粉色板鞋, 0.8552)
- [discord_noise] 勾af 联名OFF休闲防滑板鞋(多色合集) / `` -> expected `7711016729`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.8315)
- [clean_web] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.6124)
- [clean_web] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7109)
- [clean_web] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7712698523` (勾3 aj3黑猫, 0.6005)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7713967326` (勾n HotStep2气垫运动鞋(基础色合集), 0.6998)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7713673587` (勾n ly联名 A*ir *orce 1 Low series, 0.5506)
- [discord_noise] 勾dg 板鞋(三色合集) / `` -> expected `7710979345`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.8315)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7711058275` (勾n shoxRide2运动鞋(四色合集), 0.6504)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.6124)
- [clean_web] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7714032296` (勾dg 联名DunkSB低帮板鞋, 0.8264)
- [discord_noise] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.6332)
- [discord_noise] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.5574)
- [discord_noise] 勾dg 板鞋(多色/品牌联名合集) / `` -> expected `7713998068`, predicted `7714063870` (勾n HotStepTerra运动跑步鞋, 0.6815)
- [discord_noise] 勾n VapormaxFlyknit气垫鞋 / `` -> expected `7713979464`, predicted `7713998250` (勾n zoom阿尔法跑步鞋(多色合集), 0.6816)
- [clean_web] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `7713967542`, predicted `7714044088` (勾1 UN联名板鞋, 0.7787)
- [discord_noise] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `7713967542`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.7474)
- [discord_noise] 勾n Max90气垫运动鞋(多色合集) / `` -> expected `7713967542`, predicted `7713979464` (勾n VapormaxFlyknit气垫鞋, 0.7612)
- [clean_web] 勾1 粉色板鞋 / `` -> expected `7714063684`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7938)
- [clean_web] 勾1 粉色板鞋 / `` -> expected `7714063684`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7212)
- [discord_noise] 勾1 粉色板鞋 / `` -> expected `7714063684`, predicted `7713673587` (勾n ly联名 A*ir *orce 1 Low series, 0.6757)
- [discord_noise] 勾1 粉色板鞋 / `` -> expected `7714063684`, predicted `7716766172` (勾1 JOR*AN 1 D*I*O*R联名, 0.7883)
- [discord_noise] 勾1 粉色板鞋 / `` -> expected `7714063684`, predicted `7713998068` (勾dg 板鞋(多色/品牌联名合集), 0.6924)

## Dataset Failures

None.
