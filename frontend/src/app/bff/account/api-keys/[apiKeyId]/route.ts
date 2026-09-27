import { NextRequest } from "next/server";

import { authServiceRequest } from "../../_lib";

type RouteContext = {
  params: Promise<{ apiKeyId: string }>;
};

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { apiKeyId } = await context.params;
  return authServiceRequest(`/api-keys/${encodeURIComponent(apiKeyId)}`, {
    method: "PATCH",
    body: () => request.json(),
    errorDetail: "Failed to rename API key"
  });
}

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const { apiKeyId } = await context.params;
  return authServiceRequest(`/api-keys/${encodeURIComponent(apiKeyId)}`, {
    method: "DELETE",
    errorDetail: "Failed to revoke API key"
  });
}
