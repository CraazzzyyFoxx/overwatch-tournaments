import { toBlob } from "html-to-image";

/**
 * Rasterising a DOM node to a PNG — the parts that are the same wherever the
 * capture happens.
 *
 * Two shapes use it. The tournament balancer's export dialog rasterises an
 * off-screen clone, because a balance is chunked into groups of ten teams and
 * so has an export layout nothing on screen matches. A mix has two teams and a
 * fullscreen board that IS the export layout, so `useNodeCapture` rasterises a
 * live node instead — same rasteriser, same clipboard rules, same
 * image-settling wait.
 */

/**
 * Canvas flood colour for the rasterised PNG. `html-to-image` hands this
 * straight to the canvas, so it must be a literal colour — a `var()` reference
 * has no element to resolve against there. Mirrors `--aqt-bg`; the captured DOM
 * itself uses the token, which resolves because the clone inherits computed
 * styles from the live document.
 */
export const EXPORT_BACKGROUND = "#090a10";

/**
 * A 1x1 fully transparent RGBA PNG, substituted for an image the rasteriser
 * cannot read. Verified transparent: an opaque or tinted pixel here paints a
 * coloured box where the crest was, which reads as a bug rather than an
 * omission.
 */
const TRANSPARENT_PIXEL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==";

/**
 * Rasterise `node` to a PNG.
 *
 * `imagePlaceholder` is unconditional, and that is load-bearing rather than
 * defensive. `html-to-image` re-fetches every image to embed it as a data URL,
 * and an image whose fetch fails becomes `src=""` — which makes the serialised
 * SVG itself fail to decode and throws away the WHOLE capture. Measured against
 * the live asset bucket while it still lacked CORS: no placeholder threw,
 * placeholder yielded the card minus the crest. A crest beside a name and a
 * rating is a decoration; the card is the payload.
 *
 * It is also why the placeholder must not be applied conditionally or as a
 * retry: `html-to-image` memoises each resource's outcome per URL with the query
 * string stripped, so one placeholder-less attempt poisons every later attempt
 * in the same page with the empty result.
 *
 * Whether a given image embedded is deliberately NOT reported. It used to be
 * inferred from the image being cross-origin, which stopped being true the
 * moment the bucket started sending `Access-Control-Allow-Origin` — a warning
 * that fires on a host name rather than on an outcome is worse than silence.
 */
export async function capturePngBlob(node: HTMLElement): Promise<Blob> {
  const blob = await toBlob(node, {
    cacheBust: true,
    backgroundColor: EXPORT_BACKGROUND,
    pixelRatio: 2,
    imagePlaceholder: TRANSPARENT_PIXEL,
  });

  if (!blob) {
    throw new Error("Could not create PNG blob");
  }

  return blob;
}

export async function copyImageBlob(blob: Blob): Promise<void> {
  if (
    !navigator.clipboard ||
    typeof navigator.clipboard.write !== "function" ||
    typeof ClipboardItem === "undefined"
  ) {
    throw new Error("Clipboard image copy is not supported");
  }

  await navigator.clipboard.write([
    new ClipboardItem({
      "image/png": blob,
    }),
  ]);
}

/**
 * A blob as bare base64, no data-URL prefix — how an image travels in a JSON
 * request body.
 *
 * `FileReader` rather than `btoa` over the bytes: a screenshot is hundreds of
 * kilobytes, and the usual `String.fromCharCode(...bytes)` spread to feed
 * `btoa` blows the argument limit at that size.
 */
export async function blobToBase64(blob: Blob): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error ?? new Error("Could not read blob"));
    reader.readAsDataURL(blob);
  });

  return dataUrl.slice(dataUrl.indexOf(",") + 1);
}

/** Two frames: one to flush the mutation, one to let layout settle on it. */
export async function waitForLayout(): Promise<void> {
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

/**
 * Resolve once every `<img>` under `node` has settled. `error` resolves too —
 * a missing crest should cost that one glyph, not the whole capture.
 */
export async function waitForImages(node: HTMLElement): Promise<void> {
  const imageElements = Array.from(node.querySelectorAll("img"));

  await Promise.all(
    imageElements.map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }

          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        }),
    ),
  );
}
