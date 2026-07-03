import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, act, waitFor, fireEvent } from "@testing-library/react";

const saveAttachment = vi.fn(async () => {});
vi.mock("../../platform", () => ({
  saveAttachment: (...a: unknown[]) => saveAttachment(...a),
  showInFolder: vi.fn(),
  openFileWithDefault: vi.fn(),
  IS_TAURI: false,
}));
vi.mock("../../platform/auth", () => ({ getAccessToken: () => "test-token" }));
vi.mock("../../views/chat/hooks/useMdModules", () => ({ useMdModules: () => null }));

const safeFetch = vi.fn(async () => ({ ok: true, status: 200 } as unknown as Response));
vi.mock("../../providers", () => ({ safeFetch: (...a: unknown[]) => safeFetch(...(a as [string])) }));

import { FileAttachmentCard } from "../FileAttachmentCard";

describe("FileAttachmentCard PDF preview (test18)", () => {
  beforeEach(() => {
    saveAttachment.mockClear();
    safeFetch.mockClear();
  });

  it("previews a PDF via a direct authed inline URL (CSP-allowed), not blob, and does NOT download", async () => {
    const { getByTitle } = render(
      <FileAttachmentCard
        file={{ filename: "最终报告.pdf", file_path: "D:/o/最终报告.pdf" }}
        apiBaseUrl="http://test"
      />,
    );
    // The primary click is preview (docKind), not download.
    const previewBtn = getByTitle("点击预览 · 右键更多操作");
    await act(async () => { fireEvent.click(previewBtn); });

    // The preview modal is portaled to document.body, not the render container.
    await waitFor(() => {
      const iframe = document.body.querySelector("iframe");
      expect(iframe).not.toBeNull();
      const src = iframe?.getAttribute("src") || "";
      // Direct backend inline URL (CSP frame-src allows the local origin),
      // carrying the middleware ?token= so online auth passes. NOT a blob: URL
      // (which the Tauri CSP frame-src blocks).
      expect(src).not.toMatch(/^blob:/);
      expect(src).toContain("inline=1");
      expect(src).toContain("token=test-token");
    });
    // A bare PDF preview must not fetch the body itself (the iframe does) and
    // must never trigger a download.
    expect(safeFetch).not.toHaveBeenCalled();
    expect(saveAttachment).not.toHaveBeenCalled();
  });
});
