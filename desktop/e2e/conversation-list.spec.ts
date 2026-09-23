import { expect, test, type Page } from "@playwright/test";

interface ConversationHarness {
  setCharacterCount?: (count: number) => void;
  setAssistantCount?: (count: number) => void;
  setCount?: (count: number) => void;
  growLatest: (suffix: string) => void;
  streamLatest: (count: number) => Promise<void>;
}

declare global {
  interface Window {
    conversationHarness: ConversationHarness;
  }
}

async function waitForPaint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function sampleRows(page: Page, selector: string) {
  return page.evaluate(async (scrollSelector) => {
    const frames: Array<{ scrollTop: number; rows: Array<{ key: string; top: number; bottom: number }> }> = [];
    for (let frame = 0; frame < 8; frame += 1) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const scroll = document.querySelector<HTMLElement>(scrollSelector);
      if (!scroll) throw new Error(`Missing scroll container: ${scrollSelector}`);
      frames.push({
        scrollTop: scroll.scrollTop,
        rows: Array.from(scroll.querySelectorAll<HTMLElement>("[data-timeline-key]"), (row) => {
          const rect = row.getBoundingClientRect();
          return { key: row.dataset.timelineKey ?? "", top: rect.top, bottom: rect.bottom };
        }),
      });
    }
    return frames;
  }, selector);
}

async function streamAndSample(page: Page, selector: string, anchorKey: string) {
  return page.evaluate(async ({ scrollSelector, key }) => {
    const scroll = document.querySelector<HTMLElement>(scrollSelector);
    if (!scroll) throw new Error(`Missing scroll container: ${scrollSelector}`);
    const stream = window.conversationHarness.streamLatest(12);
    const frames: Array<{
      scrollTop: number;
      anchorTop: number | null;
      rows: Array<{ key: string; top: number; bottom: number }>;
    }> = [];
    for (let frame = 0; frame < 12; frame += 1) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const scrollRect = scroll.getBoundingClientRect();
      const anchor = Array.from(scroll.querySelectorAll<HTMLElement>("[data-timeline-key]"))
        .find((row) => row.dataset.timelineKey === key);
      frames.push({
        scrollTop: scroll.scrollTop,
        anchorTop: anchor ? anchor.getBoundingClientRect().top - scrollRect.top : null,
        rows: Array.from(scroll.querySelectorAll<HTMLElement>("[data-timeline-key]"), (row) => {
          const rect = row.getBoundingClientRect();
          return { key: row.dataset.timelineKey ?? "", top: rect.top, bottom: rect.bottom };
        }),
      });
    }
    await stream;
    return frames;
  }, { scrollSelector: selector, key: anchorKey });
}

function expectNoOverlap(frames: Awaited<ReturnType<typeof sampleRows>>): void {
  expect(frames.length).toBeGreaterThan(0);
  for (const frame of frames) {
    for (let index = 1; index < frame.rows.length; index += 1) {
      expect(
        frame.rows[index]!.top,
        `rows ${frame.rows[index - 1]!.key} and ${frame.rows[index]!.key} overlap at scrollTop=${frame.scrollTop}`,
      ).toBeGreaterThanOrEqual(frame.rows[index - 1]!.bottom - 0.5);
    }
  }
}

test("desktop keeps measured rows separate, preserves the reading anchor, and restores follow mode", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
    console.error(`Desktop browser page error: ${error.stack ?? error.message}`);
  });
  await page.goto("http://127.0.0.1:1422/e2e/desktop-list.html");
  await page.waitForFunction(() => window.conversationHarness !== undefined);

  const characterScroll = page.locator(".pane-character .message-scroll");
  await expect(characterScroll.locator("[data-message-source]")).toHaveCount(39, { timeout: 20_000 });
  await page.evaluate(() => window.conversationHarness.setCharacterCount?.(40));
  await expect(characterScroll.locator("[data-message-source]")).toHaveCount(40);
  const rowAtBoundary = characterScroll.locator('[data-timeline-key$="message:message-39"]');
  await expect(rowAtBoundary).toBeAttached();
  const rowHandle = await rowAtBoundary.evaluateHandle((row) => row);
  await page.evaluate(() => window.conversationHarness.setCharacterCount?.(41));
  await expect(rowAtBoundary).toBeAttached();
  expect(await rowAtBoundary.evaluate((row, previous) => row === previous, rowHandle)).toBe(true);

  await page.evaluate(() => window.conversationHarness.setCharacterCount?.(500));
  await expect.poll(() => characterScroll.locator("[data-message-source]").count()).toBeLessThan(500);
  await waitForPaint(page);
  expectNoOverlap(await sampleRows(page, ".pane-character .message-scroll"));

  await characterScroll.hover();
  await page.mouse.wheel(0, -420);
  await expect(characterScroll).toHaveAttribute("data-following-latest", "false");
  const desktopAnchor = await characterScroll.evaluate((scroll) => {
    const viewportTop = scroll.getBoundingClientRect().top;
    const row = Array.from(scroll.querySelectorAll<HTMLElement>("[data-timeline-key]")).find(
      (candidate) => candidate.getBoundingClientRect().bottom > viewportTop,
    );
    if (!row?.dataset.timelineKey) return null;
    return { key: row.dataset.timelineKey, top: row.getBoundingClientRect().top };
  });
  if (!desktopAnchor) throw new Error("Missing desktop reading anchor");
  const anchorKey = desktopAnchor.key;
  const anchorTop = desktopAnchor.top;
  const scrollTop = await characterScroll.evaluate((node) => node.getBoundingClientRect().top);
  const readingScrollTop = await characterScroll.evaluate((node) => node.scrollTop);
  const streamFrames = await streamAndSample(page, ".pane-character .message-scroll", anchorKey);
  expectNoOverlap(streamFrames);
  expect(streamFrames).toHaveLength(12);
  for (const frame of streamFrames) {
    expect(frame.anchorTop).not.toBeNull();
    expect(Math.abs((frame.anchorTop ?? Infinity) - (anchorTop - scrollTop))).toBeLessThanOrEqual(2);
    expect(Math.abs(frame.scrollTop - readingScrollTop)).toBeLessThanOrEqual(1);
  }
  const restoredAnchor = characterScroll.locator(`[data-timeline-key="${anchorKey}"]`);
  await expect(restoredAnchor).toBeAttached();
  const restoredTop = await restoredAnchor.evaluate((row) => row.getBoundingClientRect().top);
  expect(Math.abs(restoredTop - anchorTop)).toBeLessThanOrEqual(2);

  const desktopJump = page.locator(".pane-character .scroll-latest-btn");
  await expect(desktopJump).toBeVisible();
  await expect(desktopJump).toBeInViewport();
  await desktopJump.click();
  await expect(characterScroll).toHaveAttribute("data-following-latest", "true");
  await expect.poll(() => characterScroll.evaluate((element) =>
    element.scrollHeight - element.clientHeight - element.scrollTop,
  )).toBeLessThanOrEqual(2);

  const assistantScroll = page.locator(".pane-workbench .message-scroll");
  await page.evaluate(() => window.conversationHarness.setAssistantCount?.(100));
  await assistantScroll.hover();
  await page.mouse.wheel(0, -9_000);
  await expect(assistantScroll).toHaveAttribute("data-following-latest", "false");
  const toolRow = assistantScroll.locator('[data-timeline-key$="tool:tool-0"]');
  await expect(toolRow).toBeAttached();
  await toolRow.getByRole("button", { name: /工具调用/ }).click();
  await expect(toolRow.locator(".tool-expanded-body")).toBeVisible();
  await page.mouse.wheel(0, 9_000);
  await expect(toolRow).not.toBeAttached();
  await page.mouse.wheel(0, -9_000);
  await expect(toolRow).toBeAttached();
  await expect(toolRow.locator(".tool-expanded-body")).toBeVisible();

  expect(pageErrors).toEqual([]);
});

test("mobile holds the reader position through simulated streaming and scrolls only after user action", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
    console.error(`Mobile browser page error: ${error.stack ?? error.message}`);
  });
  await page.goto("http://127.0.0.1:1423/e2e/mobile-list.html");

  const scroll = page.locator(".mobile-chat-scroll");
  await expect.poll(() => scroll.locator("[data-message-id]").count()).toBeGreaterThan(0);
  await page.evaluate(() => window.conversationHarness.setCount?.(500));
  await expect.poll(() => scroll.locator("[data-message-id]").count()).toBeLessThan(500);
  await waitForPaint(page);
  expectNoOverlap(await sampleRows(page, ".mobile-chat-scroll"));

  await scroll.hover();
  await page.mouse.wheel(0, -390);
  await expect(scroll).toHaveAttribute("data-following-latest", "false");
  const mobileAnchor = await scroll.evaluate((node) => {
    const viewportTop = node.getBoundingClientRect().top;
    const row = Array.from(node.querySelectorAll<HTMLElement>("[data-timeline-key]")).find(
      (candidate) => candidate.getBoundingClientRect().bottom > viewportTop,
    );
    if (!row?.dataset.timelineKey) return null;
    return { key: row.dataset.timelineKey, top: row.getBoundingClientRect().top };
  });
  if (!mobileAnchor) throw new Error("Missing mobile reading anchor");
  const anchorKey = mobileAnchor.key;
  const before = mobileAnchor.top;
  const scrollTop = await scroll.evaluate((node) => node.getBoundingClientRect().top);
  const readingScrollTop = await scroll.evaluate((node) => node.scrollTop);
  const streamFrames = await streamAndSample(page, ".mobile-chat-scroll", anchorKey);
  expectNoOverlap(streamFrames);
  expect(streamFrames).toHaveLength(12);
  for (const frame of streamFrames) {
    expect(frame.anchorTop).not.toBeNull();
    const anchorDrift = Math.abs((frame.anchorTop ?? Infinity) - (before - scrollTop));
    expect(anchorDrift, `mobile anchor drift at scrollTop=${frame.scrollTop}: ${JSON.stringify(frame)}`).toBeLessThanOrEqual(2);
    expect(Math.abs(frame.scrollTop - readingScrollTop), `mobile scrollTop changed: ${JSON.stringify(frame)}`).toBeLessThanOrEqual(1);
  }
  const sameAnchor = scroll.locator(`[data-timeline-key="${anchorKey}"]`);
  const after = await sameAnchor.evaluate((row) => row.getBoundingClientRect().top);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(2);

  const mobileJump = page.locator(".mobile-chat-container .mobile-jump-latest");
  await expect(mobileJump).toBeVisible();
  await expect(mobileJump).toBeInViewport();
  await mobileJump.click();
  await expect(scroll).toHaveAttribute("data-following-latest", "true");
  expect(pageErrors).toEqual([]);
});
