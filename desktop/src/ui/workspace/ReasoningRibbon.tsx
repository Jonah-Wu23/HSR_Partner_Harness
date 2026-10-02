import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface ReasoningRibbonProps {
  /** 思考增量文本（后端只推干净 reasoning，原始 JSON 永不进这里）。 */
  text: string;
  /** 思考是否仍在进行。 */
  streaming: boolean;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
}

/**
 * 思考缎带：细高内联块，脉动点 + 打字机增量；高度封顶 120px 内部滚动，
 * 不顶动下方内容。结束自动折叠成一行摘要，点击重新展开。
 */
export function ReasoningRibbon({ text, streaming, expanded: controlledExpanded, onExpandedChange }: ReasoningRibbonProps) {
  const [localExpanded, setLocalExpanded] = useState(streaming);
  const expanded = controlledExpanded ?? localExpanded;
  const previousStreamingRef = useRef(streaming);
  const setExpanded = (next: boolean) => {
    setLocalExpanded(next);
    onExpandedChange?.(next);
  };
  const bodyRef = useRef<HTMLDivElement>(null);

  // 流式期间始终贴底，呈现打字机效果；在绘制前完成，新文字不会先在旧位置闪一帧。
  useLayoutEffect(() => {
    if (!streaming) return;
    const body = bodyRef.current!;
    body.scrollTop = body.scrollHeight;
  }, [text, streaming]);

  // 思考结束自动收成摘要。受控时外部按 streaming 给出默认展开值，这里只收起本地状态。
  useEffect(() => {
    if (previousStreamingRef.current && !streaming) setLocalExpanded(false);
    previousStreamingRef.current = streaming;
  }, [streaming]);

  if (!streaming && !text) return null;

  return (
    <div className={`reasoning-ribbon${streaming ? " is-streaming" : ""}`}>
      {streaming || expanded ? (
        <>
          <div className="reasoning-ribbon-head">
            {streaming ? (
              <>
                <span className="reasoning-ribbon-dot" aria-hidden />
                <span>正在思考…</span>
              </>
            ) : (
              <button type="button" className="reasoning-ribbon-toggle" onClick={() => setExpanded(false)}>
                思考完成 · 收起
              </button>
            )}
          </div>
          <div className="reasoning-ribbon-body" ref={bodyRef} data-internal-scroll>
            {text}
            {streaming ? <span className="msg-streaming-caret" aria-hidden /> : null}
          </div>
        </>
      ) : (
        <button type="button" className="reasoning-ribbon-toggle" onClick={() => setExpanded(true)}>
          思考完成 · 展开
        </button>
      )}
    </div>
  );
}
