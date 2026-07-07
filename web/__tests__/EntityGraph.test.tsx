// R-UI-8 · Per-answer entity graph: named, typed nodes + edges from evidence.subgraph.
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import EntityGraph from "@/components/EntityGraph";

const subgraph = {
  nodes: [
    { id: "e1", name: "Acme Corp", type: "Company" },
    { id: "e2", name: "Cloud Services", type: "Segment" },
  ],
  edges: [{ src: "e1", dst: "e2", type: "HAS_SEGMENT" }],
};

describe("EntityGraph (R-UI-8)", () => {
  it("renders entity names and at least one edge from the subgraph", () => {
    // New prop shape `subgraph` (names/types/edges) — red: current EntityGraph takes `entityIds`.
    render(<EntityGraph subgraph={subgraph} />);
    expect(screen.getByText(/Acme Corp/)).toBeInTheDocument();
    expect(screen.getByText(/Cloud Services/)).toBeInTheDocument();
    // an edge line is drawn (SVG <line>), beyond the radial spokes
    expect(document.querySelectorAll("line").length).toBeGreaterThanOrEqual(1);
  });
});
