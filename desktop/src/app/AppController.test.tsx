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

  it("boots from MockBackend and exposes a stable skeleton", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    render(
      <AppController
        backend={backend}
        actions={controller.actions}
        loadBootstrap={controller.loadBootstrap}
      />,
    );
    await waitFor(() => expect(screen.getByTestId("backend-status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("project-name")).toHaveTextContent("星穹项目");
    expect(screen.getByTestId("message-count")).toHaveTextContent("2");
  });
});
