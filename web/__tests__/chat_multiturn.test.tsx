// R-UI-7 · Chat holds multiple turns in one session (in-tab history).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

// Mock the streaming client so the test is deterministic and offline.
vi.mock("@/lib/api", () => ({
  listKbs: vi.fn(async () => [
    { id: "kb_a", name: "Acme", domain_id: "sec_financial", created_at: "2026-01-01T00:00:00Z" },
  ]),
  streamQuery: vi.fn(async (_kb: unknown, query: string, h: any) => {
    h.onToken?.(`answer to: ${query}`);
    h.onDone?.({ text: `answer to: ${query}`, claims: [], refused: false }, {
      subquery: query, chunks: [], entity_ids: [], graph_expanded: false,
    });
  }),
}));

import ChatPage from "@/app/chat/page";

describe("Chat multi-turn (R-UI-7)", () => {
  it("keeps the first turn when a second question is asked", async () => {
    render(<ChatPage />);
    const box = screen.getByPlaceholderText(/ask/i);

    await userEvent.type(box, "first question{enter}");
    await waitFor(() => expect(screen.getByText(/first question/)).toBeInTheDocument());

    await userEvent.type(box, "second question{enter}");
    await waitFor(() => expect(screen.getByText(/second question/)).toBeInTheDocument());

    // Both turns coexist — red today: ChatPage keeps a single `turn`, not a `turns[]` thread.
    expect(screen.getByText(/first question/)).toBeInTheDocument();
    expect(screen.getByText(/answer to: first question/)).toBeInTheDocument();
    expect(screen.getByText(/answer to: second question/)).toBeInTheDocument();
  });
});
