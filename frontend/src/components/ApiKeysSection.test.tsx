import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ApiKeysSection } from "./ApiKeysSection";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

const ROW = { id: "k1", name: "ci", prefix: "abcd1234", scope: "read", created_at: "2026-11-01T00:00:00Z", last_used_at: null };

describe("ApiKeysSection", () => {
  it("lists keys without any plaintext", async () => {
    server.use(http.get("/api/v1/api-keys", () => HttpResponse.json([ROW])));
    renderWithProviders(<ApiKeysSection />);
    expect(await screen.findByText("ci")).toBeInTheDocument();
    expect(screen.getByText("lm_abcd1234…")).toBeInTheDocument();
    expect(screen.getByText("never used")).toBeInTheDocument();
  });

  it("creates a key, shows the plaintext once, and dismisses it", async () => {
    const user = userEvent.setup();
    let body: unknown;
    server.use(
      http.post("/api/v1/api-keys", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...ROW, key: "lm_abcd1234-secret" }, { status: 201 });
      }),
    );
    renderWithProviders(<ApiKeysSection />);
    await user.type(screen.getByLabelText("Key name"), "ci");
    await user.selectOptions(screen.getByLabelText("Key scope"), "write");
    await user.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByText("lm_abcd1234-secret")).toBeInTheDocument();
    expect(screen.getByText(/will not be shown again/)).toBeInTheDocument();
    expect(body).toEqual({ name: "ci", scope: "write" });
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("lm_abcd1234-secret")).not.toBeInTheDocument();
  });

  it("revokes only after in-page confirmation", async () => {
    const user = userEvent.setup();
    let revoked = false;
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(revoked ? [] : [ROW])),
      http.delete("/api/v1/api-keys/:id", () => {
        revoked = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<ApiKeysSection />);
    await user.click(await screen.findByRole("button", { name: "Revoke ci" }));
    expect(revoked).toBe(false);
    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revoked).toBe(true));
    expect(await screen.findByText("No API keys yet.")).toBeInTheDocument();
  });
});
