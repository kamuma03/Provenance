// R-UI-4 · Honest-refusal card shows the Critic verdict + ungrounded claim, no fabricated cite.
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import RefusalCard from "@/components/RefusalCard"; // red: does not exist yet

describe("RefusalCard (R-UI-4)", () => {
  it("renders the refusal reason and the specific ungrounded claim(s)", () => {
    render(
      <RefusalCard
        refusalReason="claims remained ungrounded after 3 iterations"
        ungroundedClaims={["FY2027 revenue is $X"]}
        suggestions={["FY2025 revenue guidance"]}
      />,
    );
    expect(screen.getByText(/not supported|ungrounded|not support/i)).toBeInTheDocument();
    expect(screen.getByText(/FY2027 revenue is \$X/)).toBeInTheDocument();
    expect(screen.getByText(/FY2025 revenue guidance/)).toBeInTheDocument();
    // no citation chip is rendered in a refusal
    expect(document.querySelector(".cite")).toBeNull();
  });
});
