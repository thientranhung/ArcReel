import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CostEstimateBadge } from "./BatchAdmissionSummary";
import type { WorkflowCostEstimate } from "@/types/workflow";

function estimate(overrides: Partial<WorkflowCostEstimate> = {}): WorkflowCostEstimate {
  return {
    units: {},
    total: { amount: 1, currency: "USD" },
    unpriced_units: [],
    threshold: "ok",
    ...overrides,
  };
}

describe("CostEstimateBadge", () => {
  it("renders nothing when threshold is ok", () => {
    const { container } = render(<CostEstimateBadge costEstimate={estimate({ threshold: "ok" })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when cost_estimate is absent", () => {
    const { container } = render(<CostEstimateBadge costEstimate={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the total when threshold is warn", () => {
    render(
      <CostEstimateBadge
        costEstimate={estimate({ threshold: "warn", total: { amount: 6, currency: "USD" } })}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("$6.00");
  });

  it("shows the total and mentions confirmation when threshold is confirm", () => {
    render(
      <CostEstimateBadge
        costEstimate={estimate({ threshold: "confirm", total: { amount: 25, currency: "USD" } })}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("$25.00");
  });

  it("mentions unpriced units when present", () => {
    render(
      <CostEstimateBadge
        costEstimate={estimate({
          threshold: "warn",
          total: { amount: 6, currency: "USD" },
          unpriced_units: ["E1S02"],
        })}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/1/);
  });
});
