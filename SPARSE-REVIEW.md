# 稀疏更正交接

现有整班流程、原业务接口和运行方式见 `README.md`。本次甲站指合同班次登记中的第一站，乙站指第二站。站库和中心库各自办理。时间窗、票号、标识、用量、需量与等额达标规则沿用整班流程。

## 站端封存

在 `metering` 新增 `correct_station_sparse(store, parent_revision, new_revision, corrections)`，沿用 `correct_station` 的原窗票据更正参数、错误类别和 `StationClose` 返回类型。首份稀疏修订以甲站完整固定件为锚，从稀疏父修订继续更正时沿用该父修订的锚。一次更正可涉及多张原票，同一改窗只交一份该窗更正后的甲站合计。显式更正即确认该窗的新出处，合计为零或与父修订相同也照收。`build_station_packet` 和 `read_station_packet` 复领先前封存的原字节。

稀疏件只交付本次所改窗口的合计量及必要的分支证明。包使用规范 UTF-8 JSON，保留合同、班次、站、修订与件号的身份规则。实现可自行安排稀疏字段和证据结构，须能区别整班件与稀疏件。站端是原窗更正事实的来源。证据须界定锚件及目标枝，并使中心核对仍供数的实收与预期原件内容身份一致。

## 实收与签报

`accept_packet(store, raw_bytes)` 办理两类件的实收。登记口径或件本身非法时抛 `ValueError`。稀疏件可先于其锚件和父件收到。实收保存原件，同字节重投复领首执，同号异文抛 `ValueError`。`get_receipt` 和 `find_receipt` 沿用原业务接口。

在 `metering` 新增 `issue_sparse(store, baseline_id, anchor_receipt, target_receipt, other_receipt)`。后三项为中心实收号，依次指定甲站完整锚件、甲站稀疏目标件、乙站整班件。合法的显式查询号查无记录仍抛 `KeyError`。三个指定件都须属于冻结基荷的合同班次和注册窗序，目标须归属于所选锚件。各窗取该目标枝最后一次显式更正，未改窗取锚件。每个窗量须取自确切的实际供数原件。旁枝和同号异内容均无替代资格。

缺交的中间件若所有改窗均已被后件覆盖，且锚件和实际供数的原件都能核实，中心应签发。若缺少仍供数的原件，或指定件、分支与实收原件的归属无法核对，抛 `ValueError`。`issue_fixed` 继续接受整班件，混入稀疏件时拒签。拒签或提交失败不新增报告或签报回执，已收站件可继续复领。提交失败沿用原 SQLite 异常。

签报沿注册窗序叠加基荷与两站窗量，十五分钟窗的整数 kWh 乘 4 得到 kW，取峰值比较合同限值。`issue_sparse` 返回的记录与重开后的 `read_report(store, report_id)` 领到同一签存结果。稀疏报告公开 `report_id`、`ack`、`contract_id`、`shift_id`、`baseline_id`、`windows`、`baseline_kwh`、`usage_kwh`、`window_kw`、`peak_kw`、`limit_kw`、`over_limit`、`anchor_receipt_id`、`target_receipt_id`、`other_receipt_id` 和 `window_receipts`。序列字段为元组。`window_receipts` 每项为 `(甲站供数实收号, 乙站供数实收号)`，按注册窗序排列。`get_report_receipt` 可复领同次 `ack`。原整班签报、读回与导出继续兼容旧件和旧报告。

## 三窗交班样例

`samples/sparse-shift.json` 给出班次、零基荷、甲站完整锚件 A0 的三张票、乙站整班件 B0 的空票清单，以及按办理顺序排列的 `corrections`。每项含 `parent`、`revision` 和原窗票据映射 `tickets`。A1 与 P 是同父旁枝，恰好把第二窗改成相同的 7 kWh。

- 两站关闭后，中心先收 A2，再收 A0、B0 和 P。A1 未交。以 A2 为目标应签出 `[1,0,4]` kWh、16 kW、达标。依次使用的甲站实收来自 A0、A2、A2。乙站三窗均来自 B0。
- 同样缺 A1，中心收到 A3 后，以 A3 为目标须拒签。补交 A1 后应签出 `[1,7,4]` kWh、28 kW、超限。甲站逐窗实收来自 A0、A1、A3。
- 以 A4 为目标，第三窗显式更正后仍为 3 kWh。应签 `[1,2,3]` kWh、12 kW、达标，第三窗从 A4 实收取值。重开中心按号领取时，每报用量和出处保持签时结果。

`comparison_history` 是同一班次的另一组独立站端输入，用于对照。其 A1 把第二窗改成 0，A2 只改第三窗。两个历史都能生成完全相同的 V1 A2 整班件。采用稀疏更正后，对照历史的 A2 缺 A1 须拒签，因为第二窗仍需引用该 A1 的实际实收。

## 运行入口

现有 `.pointwise-runtime.json` 使用 `version=1`、`kind=cli`。`setup` 为准备命令的 argv 列表，`verify` 和 `demo` 各为一条 argv。原回归由 `python3 -B check_project.py` 执行，失败时返回非零状态。`python3 -B sparse_fixture.py` 通过 V1 接口检查样例输入和整班结果。交付时让运行清单核验原回归和稀疏签报，演示漏交后可签、仍欠供数原件时拒签及补件后的复领。提交失败后的签报核验可沿用 `tests/support.py` 中的 `fail_report_commit` 和 `allow_report_commit`。
