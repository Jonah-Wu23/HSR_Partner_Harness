import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppController } from "./AppController";
import { createActionController } from "../services/actions";
import { MockDesktopBackend } from "../services/mockDesktopBackend";
import { desktopStore } from "../stores/desktopStore";

describe("AppController", () => {
  afterEach(() => {
    desktopStore.getState().setStatus("booting");
  });

  it("boots from MockBackend and renders the ViewModel-driven AppShell", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    render(
      <AppController
        backend={backend}
        actions={controller.actions}
        loadBootstrap={controller.loadBootstrap}
      />,
    );
    await waitFor(() => expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument());
    expect(screen.getByText("星穹项目")).toBeInTheDocument();
    expect(screen.getByTestId("composer")).toBeInTheDocument();
  });
});
