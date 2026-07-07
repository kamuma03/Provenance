// R-UI-6 · Detect-but-confirm card: Confirm / Change (override the domain).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import DomainConfirmCard from "@/components/DomainConfirmCard"; // red: does not exist yet

describe("DomainConfirmCard (R-UI-6)", () => {
  it("confirms the detected domain", async () => {
    const onConfirm = vi.fn();
    render(
      <DomainConfirmCard detected="sec_financial" confidence={0.94} onConfirm={onConfirm} />,
    );
    expect(screen.getByText(/sec_financial/i)).toBeInTheDocument();
    expect(screen.getByText(/94%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onConfirm).toHaveBeenCalledWith(undefined); // no override → keep detected
  });

  it("overrides the domain via Change", async () => {
    const onConfirm = vi.fn();
    render(
      <DomainConfirmCard detected="sec_financial" confidence={0.51} onConfirm={onConfirm} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /change/i }));
    await userEvent.selectOptions(screen.getByRole("combobox"), "legal_contracts");
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onConfirm).toHaveBeenCalledWith("legal_contracts"); // override recorded
  });
});
