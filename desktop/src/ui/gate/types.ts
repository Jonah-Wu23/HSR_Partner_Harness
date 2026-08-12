/* 账号门与引导的视图类型。
   对应协议 account.list / register / login 的返回形状，由 presenters 映射。 */

export interface AccountListItem {
  accountId: string;
  displayName: string;
  /** 头像：本地资源路径；为空用首字占位。 */
  avatarUrl?: string | null;
  isLastLogin: boolean;
}

export interface LoginFormState {
  password: string;
}

export interface RegisterFormState {
  displayName: string;
  password: string;
  confirmPassword: string;
}
