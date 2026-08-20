import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface QrCodeProps {
  value: string;
  size?: number;
  label?: string;
}

/** 配对接入信息二维码（qrcode 库本地生成 data URL，不经过网络）。
    生成失败如实展示错误，不渲染占位图冒充。 */
export function QrCode({ value, size = 180, label }: QrCodeProps) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    QRCode.toDataURL(value, { margin: 1, width: size })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setDataUrl(null);
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [value, size]);

  if (error) {
    return (
      <p className="field-error" role="alert">
        二维码生成失败：{error}
      </p>
    );
  }
  if (!dataUrl) return null;
  return <img src={dataUrl} width={size} height={size} alt={label ?? "配对二维码"} />;
}
