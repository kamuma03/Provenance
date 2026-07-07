// R-UI-5 · Ingestion saga stepper (7 stages) advances live.
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import SagaStepper from "@/components/SagaStepper"; // red: does not exist yet

describe("SagaStepper (R-UI-5)", () => {
  it("renders all seven saga stages and marks the active one", () => {
    render(
      <SagaStepper
        stages={[
          { name: "parse", state: "done" },
          { name: "chunk", state: "done" },
          { name: "detect", state: "done" },
          { name: "extract", state: "active", detail: "62%" },
          { name: "graph", state: "pending" },
          { name: "embed", state: "pending" },
          { name: "vector", state: "pending" },
        ]}
      />,
    );
    for (const s of ["parse", "chunk", "detect", "extract", "graph", "embed", "vector"]) {
      expect(screen.getByText(new RegExp(s, "i"))).toBeInTheDocument();
    }
    expect(screen.getByText(/62%/)).toBeInTheDocument();
  });
});
