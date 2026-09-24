"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Script from "next/script";
import Cookies from "js-cookie";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { SITE_NAME } from "@/config/site";
import {
  COOKIE_CONSENT_COOKIE,
  COOKIE_CONSENT_TTL_DAYS,
  type CookieConsentValue
} from "@/lib/site/cookie-consent";
import { useCookieConsentStore } from "@/stores/cookie-consent.store";

// `--ring` resolves to `--primary`, so the shared Button's 1px ring is
// invisible on a filled primary button. Offsetting it against the card surface
// restores the indicator, the way the footer links already do.
const CHOICE_CLASS =
  "focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-card)]";

/**
 * Drop the identifiers Google Analytics and Yandex Metrica already wrote.
 * Withdrawing consent has to remove them, not just stop loading the tag —
 * otherwise the same visitor id survives the refusal. The browser only
 * deletes a cookie when the delete names the domain that set it, and both
 * GA and Metrica pick the registrable domain, so every parent suffix of the
 * current host is tried alongside a host-only delete.
 */
function clearAnalyticsCookies() {
  const names = document.cookie
    .split("; ")
    .map((pair) => pair.split("=")[0])
    .filter((name) => name.startsWith("_ga") || name.startsWith("_ym_"));
  const labels = window.location.hostname.split(".");
  const domains = [undefined, ...labels.map((_, at) => `.${labels.slice(at).join(".")}`)];

  for (const name of names) {
    for (const domain of domains) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${
        domain ? `; domain=${domain}` : ""
      }`;
    }
  }
}

type CookieConsentProps = {
  initial: CookieConsentValue | null;
  /** Google Analytics measurement id, mounted only once analytics are accepted. Unset skips GA. */
  gaId?: string;
  /** Yandex Metrica counter id, mounted only once analytics are accepted. Unset skips Metrica. */
  ymId?: string;
};

/**
 * Analytics-consent notice plus the analytics tag it gates.
 *
 * Deliberately a labelled region and not a `Dialog`: consent is not a task the
 * visitor started, so it must not trap focus, dim the page, or block reading
 * the site. Both answers are equally reachable buttons, and until a choice
 * exists there is no dismiss affordance — a decision is what stops the notice
 * from coming back. "Cookie settings" in the footer reopens it, and then the
 * notice names the choice in force and can be closed without changing it.
 */
export default function CookieConsent({
  initial,
  gaId,
  ymId
}: Readonly<CookieConsentProps>) {
  const t = useTranslations();
  const [consent, setConsent] = useState<CookieConsentValue | null>(initial);
  const isReopened = useCookieConsentStore((state) => state.isReopened);
  const closeNotice = useCookieConsentStore((state) => state.close);

  // Not done inside the click handler: gtag.js keeps refreshing its session
  // cookie for as long as the page lives, so a clear that races it loses. After
  // the reload below the tag is gone and the delete sticks.
  useEffect(() => {
    if (consent === "declined") clearAnalyticsCookies();
  }, [consent]);

  function decide(value: CookieConsentValue) {
    Cookies.set(COOKIE_CONSENT_COOKIE, value, {
      sameSite: "lax",
      expires: COOKIE_CONSENT_TTL_DAYS
    });
    setConsent(value);
    closeNotice();

    // gtag.js cannot be unloaded once it has run, so withdrawing an acceptance
    // only takes effect after the page comes back without the tag.
    if (consent === "accepted" && value === "declined") window.location.reload();
  }

  return (
    <>
      {consent === "accepted" ? (
        <>
          {gaId ? (
            <>
              <Script id="ga-init" strategy="lazyOnload">
                {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${gaId}');`}
              </Script>
              <Script
                id="ga-src"
                strategy="lazyOnload"
                src={`https://www.googletagmanager.com/gtag/js?id=${gaId}`}
              />
            </>
          ) : null}
          {ymId ? (
            <>
              <Script id="ym-init" strategy="lazyOnload">
                {`(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
m[i].l=1*new Date();
for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
ym(${ymId}, 'init', {clickmap:true, trackLinks:true, accurateTrackBounce:true});`}
              </Script>
              <noscript>
                <div>
                  <img
                    src={`https://mc.yandex.ru/watch/${ymId}`}
                    style={{ position: "absolute", left: "-9999px" }}
                    alt=""
                  />
                </div>
              </noscript>
            </>
          ) : null}
        </>
      ) : null}

      {(consent === null || isReopened) && (
        // Pinned to the inline end on wide viewports so it never covers the
        // page's own content column; inset within the layout margins (and the
        // safe area) on narrow ones, matching the floating command bars.
        <section
          aria-labelledby="cookie-consent-title"
          className="fixed bottom-4 start-4 end-4 z-50 max-w-md rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)]/95 p-4 shadow-xl backdrop-blur animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none supports-[padding:max(0px)]:pb-[max(1rem,env(safe-area-inset-bottom))] sm:start-auto"
        >
          <div className="flex items-start justify-between gap-2">
            <h2
              id="cookie-consent-title"
              className="text-sm font-semibold text-[color:var(--aqt-fg)]"
            >
              {t("legal.cookieConsent.title")}
            </h2>

            {/* Only once a choice exists: reopening must be escapable, but an
                undecided visitor has nothing to fall back to. */}
            {consent !== null && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("common.close")}
                className={`-me-1.5 -mt-1.5 shrink-0 text-[color:var(--aqt-fg-muted)] ${CHOICE_CLASS}`}
                onClick={closeNotice}
              >
                <X aria-hidden />
              </Button>
            )}
          </div>

          <p className="mt-1.5 text-pretty text-caption leading-relaxed text-[color:var(--aqt-fg-dim)]">
            {t.rich("legal.cookieConsent.body", {
              siteName: SITE_NAME,
              privacy: (chunks) => (
                <Link
                  prefetch={false}
                  href="/privacy"
                  className="font-medium text-[color:var(--aqt-fg-muted)] underline underline-offset-2 hover:text-[color:var(--aqt-fg)]"
                >
                  {chunks}
                </Link>
              )
            })}
          </p>

          {consent !== null && (
            <p className="mt-2 text-caption font-medium text-[color:var(--aqt-fg-muted)]">
              {consent === "accepted"
                ? t("legal.cookieConsent.statusOn")
                : t("legal.cookieConsent.statusOff")}
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="button" className={CHOICE_CLASS} onClick={() => decide("accepted")}>
              {t("legal.cookieConsent.accept")}
            </Button>
            <Button
              type="button"
              variant="outline"
              className={CHOICE_CLASS}
              onClick={() => decide("declined")}
            >
              {t("legal.cookieConsent.decline")}
            </Button>
          </div>
        </section>
      )}
    </>
  );
}
