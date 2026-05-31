"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export function RegistrationStatusCard({
  isOpen,
  autoApprove,
  onChangeOpen,
  onChangeAutoApprove,
}: {
  isOpen: boolean;
  autoApprove: boolean;
  onChangeOpen: (value: boolean) => void;
  onChangeAutoApprove: (value: boolean) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Registration Status</CardTitle>
        <CardDescription>Control whether players can register for this tournament.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Accept registrations</Label>
            <p className="text-xs text-muted-foreground">
              When enabled, the registration form will be visible on the tournament page.
            </p>
          </div>
          <Switch checked={isOpen} onCheckedChange={onChangeOpen} />
        </div>
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Auto-approve</Label>
            <p className="text-xs text-muted-foreground">
              Skip manual review. Registrations are approved instantly and players are added to the pool automatically.
            </p>
          </div>
          <Switch checked={autoApprove} onCheckedChange={onChangeAutoApprove} />
        </div>
      </CardContent>
    </Card>
  );
}
