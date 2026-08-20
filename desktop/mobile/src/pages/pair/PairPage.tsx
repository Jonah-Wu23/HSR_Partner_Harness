import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.3 手机端配对页（骨架空壳，由 W4 填充）。
 *
 * TODO(W4)：扫码带入 ?ws= 与配对码（二维码 payload 与桌面端 W3 面板约定）；
 * 手动输入配对码 + 设备名作为兜底；调 useMobileStore().pair(code, deviceName)，
 * 失败（配对码过期/错误、unreachable）如实展示服务端错误，不伪造成功；
 * 配对成功后 router 回 #/list。
 */
export function PairPage() {
  const pair = useMobileStore((state) => state.pair);
  void pair;
  return (
    <main className="page" data-testid="pair-page">
      <h1 className="page-title">配对桌面端</h1>
      <p className="hint">
        骨架空壳：等待 W4 实现（见文件头 TODO）。在桌面端「设置 → 远程设备」
        生成配对码，手机端输入配对码完成配对。
      </p>
    </main>
  );
}
