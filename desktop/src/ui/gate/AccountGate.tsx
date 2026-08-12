import { useState } from "react";
import type { AccountListItem } from "./types";

interface AccountGateProps {
  accounts: AccountListItem[];
  /** 就地错误（「密码不对」「这个名字已被使用」），不清表单。 */
  error: string | null;
  busy: boolean;
  onLogin: (accountId: string, password: string) => void;
  onRegister: (displayName: string, password: string) => void;
}

/**
 * 账号门：左氛围区 + 右表单卡。
 * 登录 = 账号单选卡点选后输密码；注册 = 同卡片内表单切换，不换页。
 */
export function AccountGate({ accounts, error, busy, onLogin, onRegister }: AccountGateProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [selectedId, setSelectedId] = useState<string>(
    accounts.find((account) => account.isLastLogin)?.accountId ?? accounts[0]?.accountId ?? "",
  );
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [confirm, setConfirm] = useState("");

  const registerInvalid = !name.trim() || password.length < 4 || password !== confirm;

  return (
    <div className="account-gate">
      <div className="account-gate-ambience" aria-hidden>
        <span className="account-gate-brand">HSR Partner Harness</span>
        <span className="account-gate-slogan">一间房，两盏灯。</span>
      </div>

      <div className="account-gate-card">
        <h1>{mode === "login" ? "欢迎回来" : "注册新账号"}</h1>

        {mode === "login" ? (
          <form
            className="account-gate-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (selectedId && password) onLogin(selectedId, password);
            }}
          >
            <div className="account-list" role="radiogroup" aria-label="选择账号">
              {accounts.map((account) => (
                <button
                  key={account.accountId}
                  type="button"
                  role="radio"
                  aria-checked={selectedId === account.accountId}
                  className={`account-option${selectedId === account.accountId ? " is-selected" : ""}`}
                  onClick={() => setSelectedId(account.accountId)}
                >
                  <span className="account-avatar" aria-hidden>
                    {account.avatarUrl ? (
                      <img src={account.avatarUrl} alt="" />
                    ) : (
                      account.displayName.slice(0, 1)
                    )}
                  </span>
                  {account.displayName}
                </button>
              ))}
              <button
                type="button"
                className="account-option account-option-new"
                onClick={() => {
                  setMode("register");
                  setPassword("");
                }}
              >
                ＋ 注册新账号
              </button>
            </div>

            <label className="field">
              <span className="field-label">密码</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoFocus={accounts.length > 0}
              />
            </label>
            {error ? <p className="field-error" role="alert">{error}</p> : null}
            <button type="submit" className="btn btn-primary" disabled={busy || !selectedId || !password}>
              {busy ? "正在进入…" : "进入"}
            </button>
          </form>
        ) : (
          <form
            className="account-gate-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!registerInvalid) onRegister(name.trim(), password);
            }}
          >
            <label className="field">
              <span className="field-label">显示名称</span>
              <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
            </label>
            <label className="field">
              <span className="field-label">密码（至少 4 位）</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">确认密码</span>
              <input
                type="password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </label>
            {password && confirm && password !== confirm ? (
              <p className="field-error" role="alert">两次输入的密码不一致</p>
            ) : null}
            {error ? <p className="field-error" role="alert">{error}</p> : null}
            <div className="account-gate-actions">
              <button type="submit" className="btn btn-primary" disabled={busy || registerInvalid}>
                {busy ? "正在注册…" : "注册并进入"}
              </button>
              <button type="button" className="btn btn-outline" onClick={() => setMode("login")}>
                返回登录
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
