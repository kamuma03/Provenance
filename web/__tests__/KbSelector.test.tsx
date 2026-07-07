// R-UI-1 · Multi-KB selector replaces the raw kb_ paste.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import KbSelector from "@/components/KbSelector"; // red: component does not exist yet

const KBS = [
  { id: "kb_a", name: "Acme 10-K", domain_id: "sec_financial", created_at: "2026-01-01T00:00:00Z" },
  { id: "kb_b", name: "Contracts", domain_id: "legal_contracts", created_at: "2026-01-02T00:00:00Z" },
];

describe("KbSelector (R-UI-1)", () => {
  it("lists KBs by name and emits selected kb_ids (multi)", async () => {
    const onChange = vi.fn();
    render(<KbSelector kbs={KBS} selected={[]} onChange={onChange} />);
    expect(screen.getByText("Acme 10-K")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Acme 10-K"));
    await userEvent.click(screen.getByText("Contracts"));
    // multi-select: the final emission contains both ids
    expect(onChange).toHaveBeenLastCalledWith(["kb_a", "kb_b"]);
  });
});
