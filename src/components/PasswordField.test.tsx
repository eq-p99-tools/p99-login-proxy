import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PasswordField } from "./PasswordField";

afterEach(() => cleanup());

describe("PasswordField", () => {
  it("toggles visibility on click in default mode", () => {
    render(<PasswordField aria-label="Secret" defaultValue="hidden" />);
    const input = screen.getByLabelText("Secret") as HTMLInputElement;
    const toggle = screen.getByRole("button", { name: "Show password" });

    expect(input.type).toBe("password");
    fireEvent.click(toggle);
    expect(input.type).toBe("text");
    fireEvent.click(toggle);
    expect(input.type).toBe("password");
  });

  it("reveals only while the eye control is held", () => {
    render(
      <PasswordField
        aria-label="API Token"
        visibilityMode="hold"
        holdTip="Hold to show API token"
        defaultValue="secret-token"
      />,
    );
    const input = screen.getByLabelText("API Token") as HTMLInputElement;
    const toggle = screen.getByRole("button", { name: "Hold to show API token" });

    expect(input.type).toBe("password");
    fireEvent.pointerDown(toggle);
    expect(input.type).toBe("text");
    fireEvent.pointerUp(toggle);
    expect(input.type).toBe("password");
  });

  it("hides again when pointer leaves the hold control", () => {
    render(
      <PasswordField aria-label="API Token" visibilityMode="hold" defaultValue="secret-token" />,
    );
    const input = screen.getByLabelText("API Token") as HTMLInputElement;
    const toggle = screen.getByRole("button", { name: "Hold to show password" });

    fireEvent.pointerDown(toggle);
    expect(input.type).toBe("text");
    fireEvent.pointerLeave(toggle);
    expect(input.type).toBe("password");
  });
});
