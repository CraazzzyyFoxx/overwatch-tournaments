import { authServiceRequest } from "../_lib";

export async function GET() {
  return authServiceRequest("/sessions", { errorDetail: "Failed to load sessions" });
}
