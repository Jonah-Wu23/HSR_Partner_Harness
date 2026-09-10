# A01 现场说明

- 协议通道：候选 sidecar `--serve 8765` 的 `GET /ws`；token 由桌面端「远程设备 → 生成配对码」
  签发的六位码经 `remote.pair` 换取（本批次配对码 659304，device_name=s4-probe-01）。
- 并发测量方式：四个独立 WS 连接同一时刻 `send_str`，以 `time.monotonic()` 记录发送时刻；
  最大差值 0.0s（同一事件循环内四路写，属于真实并发提交）。
- 排队测量：同一会话 0.187s 间隔连续提交，第二条进入 `queue_items`（queued/position=0），
  回合完成后按 A→B 顺序派发。
- 取消测量：协作会话在 `approval.requested`（approval_id=5）后调用 `task.cancel`，
  取消后 active_task 归零、该会话待审批从 `approvals` 快照消失。
- 客户端修复记录：首轮测试脚本存在「响应先到而未被认领即丢弃」的缺陷，导致一次假超时；
  已改为缓存未认领响应（ph_client.py `_unclaimed`），并以修复后的脚本复测。
