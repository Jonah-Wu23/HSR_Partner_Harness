// 桌面二进制入口：应用主体在 lib.rs（Android 壳经 cdylib 加载同一 run()）。
#![cfg_attr(windows, windows_subsystem = "windows")]

fn main() {
    hsr_partner_harness_lib::run();
}
