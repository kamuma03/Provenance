// R-UI-3 · Source inspector: clicking a claim highlights its page + bbox (schematic, v1).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import SourceInspector from "@/components/SourceInspector"; // red: does not exist yet
import type { Claim } from "@/lib/types";

const claims: Claim[] = [
  {
    text: "Total revenue was $24.31B in FY2024.",
    citations: [
      {
        chunk_id: "c_0421",
        page: 42,
        bbox: { page: 42, x0: 72, y0: 512, x1: 388, y1: 536, page_width: 612, page_height: 792 },
      },
    ],
  },
];

describe("SourceInspector (R-UI-3)", () => {
  it("highlights the cited bbox when a claim is clicked", async () => {
    render(<SourceInspector claims={claims} />);
    await userEvent.click(screen.getByText(/c_0421/));
    const hl = document.querySelector(".bbox-hl") as HTMLElement | null;
    expect(hl).not.toBeNull();
    // left = x0/page_width, top = y0/page_height (normalized by the real page dims)
    expect(hl!.style.left).toContain(`${(72 / 612) * 100}`.slice(0, 4));
    expect(hl!.style.top).toContain(`${(512 / 792) * 100}`.slice(0, 4));
  });
});
