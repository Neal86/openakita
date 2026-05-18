import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

import { StaleBundleBanner } from "../StaleBundleBanner";

function makeFetchReturning(buildId: string): typeof fetch {
  return vi.fn(async () =>
    ({
      ok: true,
      status: 200,
      json: async () => ({ build_id: buildId }),
    }) as unknown as Response,
  ) as unknown as typeof fetch;
}

describe("StaleBundleBanner", () => {
  it("shows the banner when the backend build_id drifts away from the bundle", async () => {
    vi.useFakeTimers();
    const fetchImpl = makeFetchReturning("server-NEW");
    render(
      <StaleBundleBanner
        bundleId="bundle-OLD"
        apiBase="http://test"
        pollMs={1000}
        initialDelayMs={10}
        fetchImpl={fetchImpl}
      />,
    );
    expect(screen.queryByTestId("stale-bundle-banner")).toBeNull();

    // Drive the initial-delay timer + flush the awaited fetch.
    await act(async () => {
      vi.advanceTimersByTime(15);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://test/api/build-info",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getByTestId("stale-bundle-banner")).toBeInTheDocument();
    expect(screen.getByText("新版本可用，请刷新页面")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("stays hidden when the backend build_id matches the bundle", async () => {
    vi.useFakeTimers();
    const fetchImpl = makeFetchReturning("bundle-SAME");
    render(
      <StaleBundleBanner
        bundleId="bundle-SAME"
        apiBase=""
        pollMs={1000}
        initialDelayMs={10}
        fetchImpl={fetchImpl}
      />,
    );
    await act(async () => {
      vi.advanceTimersByTime(15);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("stale-bundle-banner")).toBeNull();
    vi.useRealTimers();
  });
});
