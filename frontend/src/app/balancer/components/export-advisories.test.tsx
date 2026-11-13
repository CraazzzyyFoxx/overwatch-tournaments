import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import type { createTranslator } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "@/lib/notify";
import { BalancerOperationDialog } from "./BalancerOperationDialog";
import { useBalancerMutations } from "./useBalancerMutations";

// `useBalancerMutations` is called here as a plain function, outside any provider.
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<{ createTranslator: typeof createTranslator }>();
  // `vi.mock` factories are hoisted above the file's imports, so the catalog loads here.
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never })
  };
});
vi.mock("@tanstack/react-query", () => ({ useMutation: (options: unknown) => options }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), warning: vi.fn() } }));
vi.mock("@/components/balancer/workspace-helpers", () => ({
  buildVariantFromSavedBalance: () => ({ id: "saved", source: "saved" })
}));
vi.mock("@craazzzyyfoxx/admin-kit/ui/dialog", () => {
  const Part = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return { Dialog: Part, DialogContent: Part, DialogDescription: Part, DialogFooter: Part, DialogHeader: Part, DialogTitle: Part };
});

const advisories = [
  "Alpha: skipped Missing#1234 (not found)",
  "Alpha: team_format_violation: starters_out_of_range"
];

beforeEach(() => vi.clearAllMocks());

describe("balancer export advisories", () => {
  it.each([true, false])("uses a warning toast only when advisories exist: %s", (hasAdvisories) => {
    const result = { imported_teams: 1, advisories: hasAdvisories ? advisories : [] };
    const { exportToTournamentMutation } = useBalancerMutations({
      setVariants: vi.fn(), setActiveVariantId: vi.fn()
    } as unknown as Parameters<typeof useBalancerMutations>[0]);
    const callback = exportToTournamentMutation as unknown as {
      onSuccess: (data: { savedBalance: object; exportResult: typeof result }) => void
    };
    callback.onSuccess({ savedBalance: {}, exportResult: result });
    if (hasAdvisories) {
      expect(notify.warning).toHaveBeenCalledWith("Teams exported to tournament", expect.objectContaining({
        description: expect.stringContaining(advisories.join("\n")), duration: Infinity
      }));
      expect(notify.success).not.toHaveBeenCalled();
    } else {
      expect(notify.success).toHaveBeenCalled();
      expect(notify.warning).not.toHaveBeenCalled();
    }
  });

  it("keeps every skipped member and format warning visible in the export dialog", () => {
    const html = renderToStaticMarkup(<BalancerOperationDialog
      open onOpenChange={() => {}} title="Export" description="Export teams" steps={[]}
      isRunning={false} summary="1 team exported" error={null} advisories={advisories}
    />);
    expect(html).toContain(advisories[0]);
    expect(html).toContain(advisories[1]);
    expect(html).toContain('role="status"');
  });
});
