import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CreateTicketModal from "../components/CreateTicketModal.tsx";

describe("CreateTicketModal", () => {
  it("keeps draft state local while typing in the dialog", async () => {
    const user = userEvent.setup();
    const siblingRenderSpy = vi.fn();

    function StableSibling() {
      siblingRenderSpy();
      return <div>Stable sibling</div>;
    }

    function Harness() {
      return (
        <>
          <StableSibling />
          <CreateTicketModal
            isOpen
            priorities={[{ id: "1", name: "High" }]}
            requestTypes={[{ id: "1", name: "Hardware", description: "" }]}
            isLoadingOptions={false}
            isSubmitting={false}
            errorText=""
            onClose={() => {}}
            onSubmit={() => {}}
          />
        </>
      );
    }

    render(<Harness />);
    expect(siblingRenderSpy).toHaveBeenCalledTimes(1);

    await user.type(screen.getByLabelText("Summary"), "Create a new hardware request");
    await user.type(screen.getByLabelText("Description"), "This should not rerender the ticket list.");

    expect(siblingRenderSpy).toHaveBeenCalledTimes(1);
  });
});
