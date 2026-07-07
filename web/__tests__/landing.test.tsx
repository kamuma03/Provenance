// R-UI-9 · Landing leads with the value proposition (screen 1d).
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Home from "@/app/page";

describe("Landing page (R-UI-9)", () => {
  it("shows the value-prop hero and the honest-refusal feature", () => {
    render(<Home />);
    // Redesigned hero + the three differentiators (cited-to-span, multi-hop, honest refusal).
    expect(screen.getByText(/traced to (its|a) source/i)).toBeInTheDocument();
    expect(screen.getByText(/honest refusal/i)).toBeInTheDocument(); // red: current landing lacks this
    expect(screen.getByRole("link", { name: /ingest/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /chat/i })).toBeInTheDocument();
  });
});
