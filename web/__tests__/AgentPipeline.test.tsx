// R-UI-2 · Live agent pipeline: 4 stages with state; blocked on refusal.
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import AgentPipeline from "@/components/AgentPipeline"; // red: does not exist yet

describe("AgentPipeline (R-UI-2)", () => {
  it("renders all four crew stages in order", () => {
    render(
      <AgentPipeline
        stages={[
          { name: "planner", state: "done" },
          { name: "retriever", state: "done", detail: "14 chunks · graph +6" },
          { name: "critic", state: "active" },
          { name: "synthesizer", state: "pending" },
        ]}
      />,
    );
    for (const s of ["Planner", "Retriever", "Critic", "Synthesizer"]) {
      expect(screen.getByText(new RegExp(s, "i"))).toBeInTheDocument();
    }
  });

  it("shows the Critic in a blocked state on refusal", () => {
    render(
      <AgentPipeline
        stages={[
          { name: "planner", state: "done" },
          { name: "retriever", state: "done" },
          { name: "critic", state: "blocked" },
          { name: "synthesizer", state: "pending" },
        ]}
      />,
    );
    expect(screen.getByText(/blocked/i)).toBeInTheDocument();
  });
});
