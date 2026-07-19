import { getTranslations } from "next-intl/server";

export default async function NotConfigured() {
  const t = await getTranslations();
  return (
    <div className="mx-auto max-w-md py-24 text-center">
      <h1 className="text-2xl font-semibold">{t("notConfigured.title")}</h1>
      <p className="mt-2 text-muted-foreground">
        {t("notConfigured.description")}
      </p>
    </div>
  );
}
