import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// Vitest harness for the redesign component tests (spec.md Verification table).
// jsdom env + the same `@/*` → web-root alias the app uses.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.tsx"],
    include: ["__tests__/**/*.test.tsx"],
  },
  resolve: { alias: { "@": resolve(__dirname, ".") } },
});
