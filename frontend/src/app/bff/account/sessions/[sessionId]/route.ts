import { authServiceRequest } from "../../_lib";

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await context.params;
  return authServiceRequest(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    errorDetail: "Failed to revoke session"
  });
}
