import messages from "./i18n/messages/en.json";

declare module "next-intl" {
  interface AppConfig {
    Locale: "en" | "ru";
    Messages: typeof messages;
  }
}
