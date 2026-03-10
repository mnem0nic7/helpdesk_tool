import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import KnowledgeBasePage from "../pages/KnowledgeBasePage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getRequestTypes: vi.fn(),
    getKnowledgeBaseArticles: vi.fn(),
    createKnowledgeBaseArticle: vi.fn(),
    updateKnowledgeBaseArticle: vi.fn(),
    draftKnowledgeBaseArticleFromTicket: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("KnowledgeBasePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getRequestTypes.mockResolvedValue([
      { id: "rt-1", name: "Email or Outlook", description: "" },
      { id: "rt-2", name: "Security Alert", description: "" },
    ]);
    mockApi.getKnowledgeBaseArticles.mockResolvedValue([
      {
        id: 7,
        slug: "email-or-outlook",
        code: "KB-EML-001",
        title: "Email or Outlook",
        request_type: "Email or Outlook",
        summary: "Mailbox troubleshooting guide.",
        content: "Restart Outlook and verify Exchange connectivity.",
        source_filename: "KB-EML-001_Email_or_Outlook.docx",
        source_ticket_key: "",
        imported_from_seed: true,
        ai_generated: false,
        created_at: "2026-03-10T00:00:00Z",
        updated_at: "2026-03-10T00:00:00Z",
      },
    ]);
    mockApi.draftKnowledgeBaseArticleFromTicket.mockResolvedValue({
      title: "Email Sync Troubleshooting",
      request_type: "Email or Outlook",
      summary: "Troubleshoot sync and send issues.",
      content: "Overview\n\nResolution Steps\n\nRestart Outlook.",
      model_used: "gpt-4o-mini",
      source_ticket_key: "OIT-300",
      suggested_article_id: null,
      suggested_article_title: "",
      recommended_action: "create_new",
      change_summary: "Adds Outlook restart guidance.",
    });
    mockApi.createKnowledgeBaseArticle.mockResolvedValue({
      id: 11,
      slug: "email-sync-troubleshooting",
      code: "",
      title: "Email Sync Troubleshooting",
      request_type: "Email or Outlook",
      summary: "Troubleshoot sync and send issues.",
      content: "Overview\n\nResolution Steps\n\nRestart Outlook.",
      source_filename: "",
      source_ticket_key: "OIT-300",
      imported_from_seed: false,
      ai_generated: true,
      created_at: "2026-03-10T01:00:00Z",
      updated_at: "2026-03-10T01:00:00Z",
    });
  });

  it("shows seeded articles and can draft a new KB article from a closed ticket", async () => {
    const user = userEvent.setup();

    render(<KnowledgeBasePage />);

    expect(await screen.findByText("Knowledge Base")).toBeInTheDocument();
    expect(await screen.findByText("KB-EML-001")).toBeInTheDocument();
    expect(screen.getByText("Seeded")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("OIT-12345"), "OIT-300");
    await user.click(screen.getByRole("button", { name: "Draft From Ticket" }));

    await waitFor(() => {
      expect(mockApi.draftKnowledgeBaseArticleFromTicket).toHaveBeenCalledWith("OIT-300", undefined);
    });

    await waitFor(() => {
      expect(screen.getByDisplayValue("Email Sync Troubleshooting")).toBeInTheDocument();
    });
    expect(
      screen
        .getAllByRole("textbox")
        .some((element) => (element as HTMLInputElement | HTMLTextAreaElement).value.includes("Restart Outlook.")),
    ).toBe(true);

    await user.click(screen.getByRole("button", { name: "Create Article" }));

    await waitFor(() => {
      expect(mockApi.createKnowledgeBaseArticle).toHaveBeenCalledWith({
        title: "Email Sync Troubleshooting",
        request_type: "Email or Outlook",
        summary: "Troubleshoot sync and send issues.",
        content: "Overview\n\nResolution Steps\n\nRestart Outlook.",
        source_ticket_key: "OIT-300",
      });
    });
  });
});
