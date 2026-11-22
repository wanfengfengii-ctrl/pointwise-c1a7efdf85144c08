# 海岬园区计量复核台账 V1

园区计量室用这套台账向财务交付冷站甲、泵站乙的十五分钟用量和合同需量裁决。站员保管原票并可以关库交班。财务只需中心库中的冻结基荷和两份实收件，就能签发可供次班独立领取的报告。

## 一班的办理顺序

1. 在中心和各站登记同一合同班次，填写双站、限值和按时间升序排列的窗口。
2. 中心基荷计量员开草稿并逐窗记量。实际零读数也要录入。
3. 基荷齐备后冻结具名版本，财务按该版本号选用。
4. 各站开办具名站修订，逐笔登记已定窗原票。
5. 结班保存有序逐窗合计、票号引用和固定件。交换员领取件后可以关闭站库。
6. 中心实收两站固定件。同件重投沿用首执，同号异文拒收。
7. 财务选择冻结基荷和两站实际实收，签存逐窗合计、峰值、裁决和同次回执。
8. 次班按报告号复领。原窗勘误生成新站修订，交换员重新实收后可另签新报。旧报告按原号领取。

窗口键是无时区的园区计量时间 `YYYY-MM-DDTHH:MM`。每个起点定义从该时刻起的十五分钟半开窗，也可登记显式的 `(start, end)`。相邻窗可以首尾相接，登记顺序须按起点上升。同窗基荷、甲站和乙站三项整数 kWh 相加，乘 4 得 kW。峰值取各窗最大值，等额达标。缺窗必须补记，零值照计。

## Python API

Python 3.11，使用标准库。`metering` 导出常用接口，直接传入 `Store` 实例。中心和各站各打开自己的路径，支持 `with Store(path) as store`。重复打开已有数据库保留原记录。`define_shift` 可按原定义重复登记。`amend_shift` 在冻结、结班或实收锁定口径前允许同合同勘订，并检查已登记的草稿及原票仍有归属。

| 办理 | 接口（首参数为 `store`） |
|---|---|
| 班次 | `define_shift(store, contract_id, shift_id, stations, limit_kw, windows)`、`get_shift(store, shift_id)` |
| 基荷 | `begin_baseline(store, shift_id, draft_id)`、`record_baseline_value(store, draft_id, window, kwh)`、`freeze_baseline(store, draft_id, baseline_id)`、`get_frozen_baseline(store, baseline_id)` |
| 基荷勘误 | `create_baseline_revision(store, parent_id, baseline_id, values)`，传齐每窗值的映射 |
| 站票 | `begin_station(store, shift_id, station, revision_id)`、`record_ticket(store, shift_id, station, ticket_id, window, kwh)`，或 `record_tickets(store, shift_id, station, tickets)` 批量提交 `Ticket` |
| 结班及复领 | `close_station(store, shift_id, station, revision_id)` 返回含 `packet_id` 与 `packet` 的记录。`build_station_packet(store, revision_id)` 按修订复领字节，`read_station_packet(store, packet_id)` 按件号复领 |
| 站票勘误 | `correct_station(store, parent_revision, new_revision, corrections)`，映射每个待更正票号到原窗及新值 `(window, kwh)` |
| 实收 | `accept_packet(store, raw_bytes)` 返回实收号、首执、指纹与原件。`get_receipt(store, receipt_id)` 和 `find_receipt(store, packet_id)` 按号复领 |
| 签报 | `issue_fixed(store, baseline_id, receipt_a, receipt_b)`、`read_report(store, report_id)`、`get_report_receipt(store, report_id)`、`export_report(store, report_id, format='json')`，也可选 `csv` |

班号在同一库中唯一。具名标识为 1 到 128 个字母、数字、下划线或连字符，首字必须为字母或数字，按原字符串匹配。电量与需量限值接收非负整数，布尔值不作为读数。非法值、缺窗、状态冲突、同号异文、错配或坏件抛出 `ValueError`。合法标识的查询没有记录时抛出 `KeyError`。提交错误保留 SQLite 异常，解除故障后可重新签报。

固定件使用严格规范的 UTF-8 JSON 字节，字段按键排序，紧凑分隔，中文按 UTF-8 表示。件号由合同、班次、站及站修订确定。中心保存原字节和 SHA-256 指纹，实收及报告的来源按合同双站登记顺序保存。报告复领读取签存快照。JSON 表示完整快照，CSV 按窗口列出相同计算值及来源。

## 回归与演示

平台物化工程后执行如下回归入口。

```sh
python3 -B check_project.py
```

用正常双站样例办理一班，并在各站关库后签报和复领。

```sh
python3 -B demo.py
```

样例在 `samples/two-station.json`。基荷 `[1,0]`、甲站 `[1,0]`、乙站 `[0,2]` 合计 `[2,2]`，峰值 8 kW。甲站勘误后合计 `[3,2]`，峰值 12 kW。演示使用临时数据库。`samples/legacy.sql` 是可装入新建 V1 中心库的历史行快照，含实际原件字节、冻值、首执和旧报。回归覆盖装入后重开、按号复领、实收重投及再次签报。
