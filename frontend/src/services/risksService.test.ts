import { describe, expect, it } from "vitest";
import { jsonResponse, mockFetch } from "../test/fetchMock.ts";
import { getRiskReport, startRiskDiscovery } from "./validationService.ts";

describe("risk report and discovery runs", () => {
  it("asks for a sort and a stored discovery run, never for model review", async () => {
    const { calls } = mockFetch([
      {
        method: "GET",
        path: "/api/v1/validation-runs/run_1/risks",
        respond: { risks: [] },
      },
    ]);
    await getRiskReport("run_1", {
      sortBy: "price_impact",
      sortOrder: "asc",
      discoveryRunId: "disc_1",
    });
    const query = calls[calls.length - 1].query;
    expect(Object.fromEntries(query)).toEqual({
      sort_by: "price_impact",
      sort_order: "asc",
      discovery_run_id: "disc_1",
    });
    expect(query.has("model_review")).toBe(false);
    expect(query.has("discovery")).toBe(false);
  });

  it("starts discovery in the background and tells a reused run apart", async () => {
    const path = "/api/v1/validation-runs/run_1/risks/discovery-runs";
    mockFetch([
      {
        method: "POST",
        path,
        respond: () =>
          jsonResponse({ discovery_run_id: "disc_1" }, { status: 202 }),
      },
    ]);
    await expect(startRiskDiscovery("run_1")).resolves.toEqual({
      run: { discovery_run_id: "disc_1" },
      started: true,
    });
    mockFetch([
      {
        method: "POST",
        path,
        respond: () =>
          jsonResponse({ discovery_run_id: "disc_1" }, { status: 200 }),
      },
    ]);
    await expect(startRiskDiscovery("run_1")).resolves.toEqual({
      run: { discovery_run_id: "disc_1" },
      started: false,
    });
  });
});
