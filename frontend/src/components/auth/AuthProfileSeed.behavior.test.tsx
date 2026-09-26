// @vitest-environment happy-dom
//
// The admin zone resolves `/auth/me` on the server and hands the answer to the
// client store, which is what removes the spinner + second `/auth/me` every
// admin page load used to pay. Two things have to hold for that to be safe:
// the seed must actually land, and it must never overwrite an answer the
// client already has — a profile captured while rendering a request would
// otherwise resurrect a session the user just signed out of.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthProfileSeed } from "@/components/auth/AuthProfileSeed";
import { type AuthProfile, useAuthProfileStore } from "@/stores/auth-profile.store";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

const PROFILE: AuthProfile = {
  id: 1,
  username: "probe",
  roles: ["admin"],
  permissions: [],
  denies: [],
  isSuperuser: false,
  workspaces: [],
  linkedPlayers: []
};

async function mount() {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<AuthProfileSeed profile={PROFILE} />);
  });
  await act(async () => {
    root.unmount();
  });
  container.remove();
}

beforeEach(() => {
  useAuthProfileStore.setState({
    status: "idle",
    user: undefined,
    error: undefined,
    lastFetchedAt: undefined
  });
  document.body.innerHTML = "";
});

describe("AuthProfileSeed", () => {
  it("hands an idle store the server-resolved profile", async () => {
    await mount();

    expect(useAuthProfileStore.getState().status).toBe("authenticated");
    expect(useAuthProfileStore.getState().user?.username).toBe("probe");
    // Seeded, not merely present: the freshness guard in `fetchMe` reads this,
    // and leaving it undefined would make every focus event refetch.
    expect(typeof useAuthProfileStore.getState().lastFetchedAt).toBe("number");
  });

  it("leaves a signed-out store alone instead of resurrecting the session", async () => {
    useAuthProfileStore.setState({ status: "anonymous", user: undefined });

    await mount();

    expect(useAuthProfileStore.getState().status).toBe("anonymous");
    expect(useAuthProfileStore.getState().user).toBeUndefined();
  });
});
