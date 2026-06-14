export function shouldIgnoreNavigationClick(event) {
  return (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

export function getInternalNavigationTarget(rawHref, currentOrigin) {
  if (!rawHref) {
    return null;
  }

  if (
    rawHref.startsWith("mailto:") ||
    rawHref.startsWith("tel:") ||
    rawHref.startsWith("javascript:")
  ) {
    return null;
  }

  try {
    const url = new URL(rawHref, currentOrigin);
    if (url.origin !== currentOrigin) {
      return null;
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

export function isChangedInternalNavigation(currentHref, nextHref, currentOrigin) {
  const currentTarget = getInternalNavigationTarget(currentHref, currentOrigin);
  const nextTarget = getInternalNavigationTarget(nextHref, currentOrigin);

  if (!currentTarget || !nextTarget) {
    return false;
  }

  return currentTarget !== nextTarget;
}
