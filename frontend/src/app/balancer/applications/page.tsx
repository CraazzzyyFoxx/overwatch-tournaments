import { redirect } from "next/navigation";

export default function BalancerApplicationsRedirectPage() {
  redirect("/balancer/registrations?source=google_sheets");
}
