// @vitest-environment happy-dom
// The balancer page's run panel, setup checklist, variant strip and operation dialog read their
// copy from `balancerTool.page`, so a Russian reader sees Russian rather than English literals.
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { Users } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import ru from "@/i18n/messages/ru.json";
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";

import { BalancerOperationDialog } from "./BalancerOperationDialog";
import { BalancerSetupChecklist } from "./BalancerSetupChecklist";
import { createOperationSteps } from "./operation-steps";
import { PresetRunPanel } from "./PresetRunPanel";
import { EXPORT_TO_TOURNAMENT_STEPS } from "./useBalancerLayout";
import { VariantSelector } from "./VariantSelector";

vi.mock("@craazzzyyfoxx/admin-kit/ui/dialog", () => {
  const Part = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return { Dialog: Part, DialogContent: Part, DialogDescription: Part, DialogFooter: Part, DialogHeader: Part, DialogTitle: Part };
});

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const inRussian = (node: ReactNode) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale="ru" messages={ru}>
      {node}
    </NextIntlClientProvider>
  );

const noop = () => {};

describe("balancer page in Russian", () => {
  it("words the run controls and the job card", async () => {
    // The run controls portal into the tool top-bar's slot.
    const slot = document.createElement("div");
    slot.id = "balancer-header-slot";
    const container = document.createElement("div");
    document.body.append(slot, container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="ru" messages={ru}>
          <PresetRunPanel
            counters={[{ label: "Пул", value: 3, icon: Users }]}
            presetOptions={["DEFAULT"]}
            selectedPreset="DEFAULT"
            onSelectPreset={noop}
            invalidPlayerCount={2}
            excludeInvalidPlayers={false}
            onExcludeInvalidPlayersChange={noop}
            onOpenSettings={noop}
            settingsDirty={false}
            canRunBalance
            onRunBalance={noop}
            isRunPending={false}
            onImportBalance={noop}
            isImportPending={false}
            onExportPlayers={noop}
            isExportPlayersPending={false}
            jobStatus="running"
            jobMessage={null}
            jobProgress={null}
          />
        </NextIntlClientProvider>
      );
    });

    const text = document.body.textContent ?? "";
    expect(text).toContain(ru.balancerTool.page.run.runBalance);
    expect(text).toContain("Пропустить с ошибками: 2");
    expect(text).toContain(ru.balancerTool.page.run.job);
    expect(text).toContain(ru.balancerTool.page.job.status.running);
    for (const english of ["Run balance", "Load balance JSON", "Export players", "Balance job", "Settings"]) {
      expect(text).not.toContain(english);
    }

    act(() => root.unmount());
    slot.remove();
    container.remove();
  });

  it("words the setup checklist", () => {
    const html = inRussian(
      <BalancerSetupChecklist
        poolPlayerCount={5}
        invalidPlayerCount={3}
        canRunBalance={false}
        isRunPending={false}
        onBrowseExcluded={noop}
        onReviewConflicts={noop}
        onRunBalance={noop}
      />
    );

    expect(html).toContain("5 игроков в пуле");
    expect(html).toContain("3 игроков нужно исправить");
    expect(html).toContain(ru.balancerTool.page.checklist.reviewConflicts);
    expect(html).not.toContain("Add players to pool");
    expect(html).not.toContain("Review conflicts");
  });

  it("names variants from their source, not the English fallback label", () => {
    const payload = { teams: [], statistics: null } as unknown as BalanceVariant["payload"];
    const html = inRussian(
      <VariantSelector
        variants={[
          { id: "saved-12", label: "Saved balance #12", labelSource: { kind: "saved", id: 12 }, payload, source: "saved" },
          { id: "generated-1", label: "Balance 1", labelSource: { kind: "generated", index: 1 }, payload, source: "generated" }
        ]}
        activeVariantId="saved-12"
        onSelectVariant={noop}
      />
    );

    expect(html).toContain("Сохранённый баланс #12");
    expect(html).toContain("Баланс 1");
    expect(html).toContain(ru.balancerTool.page.variantSelector.showAll);
    expect(html).not.toContain("Saved balance");
    expect(html).not.toContain("Show all");
  });

  it("names the export steps and their status", () => {
    const html = inRussian(
      <BalancerOperationDialog
        open
        onOpenChange={noop}
        title="Экспорт в турнир"
        description="—"
        steps={createOperationSteps(EXPORT_TO_TOURNAMENT_STEPS)}
        isRunning={false}
        summary={null}
        error="boom"
        onRetry={noop}
      />
    );

    expect(html).toContain(ru.balancerTool.page.operation.steps.validate.label);
    expect(html).toContain(ru.balancerTool.page.operation.stepStatus.pending);
    expect(html).toContain(ru.common.retry);
    expect(html).toContain(ru.common.close);
    for (const english of ["Validate selected balance", "Pending", "Retry", "Close"]) {
      expect(html).not.toContain(english);
    }
  });
});
