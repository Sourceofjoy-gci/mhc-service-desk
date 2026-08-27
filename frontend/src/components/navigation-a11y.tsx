/**
 * Navigation affordances that a single-page app has to provide for itself.
 *
 * Both shells render a header of up to nine controls before `<main>`. Without
 * a bypass, every keyboard and screen-reader user traverses all of it on every
 * route; and because React Router swaps the view without a document load,
 * assistive technology is otherwise never told the destination changed.
 */

import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

export const MAIN_CONTENT_ID = "main-content";

/**
 * Hidden until focused, then the first thing a keyboard user reaches.
 * WCAG 2.4.1 Bypass Blocks.
 */
export function SkipLink() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-card focus-visible:px-4 focus-visible:py-2.5 focus-visible:text-sm focus-visible:font-medium focus-visible:text-foreground focus-visible:no-underline focus-visible:shadow-md focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      Skip to main content
    </a>
  );
}

/**
 * Announces the route's own heading after navigation. The first render is
 * skipped — the browser already announces the document on initial load, and
 * repeating it is noise.
 */
export function RouteAnnouncer() {
  const { pathname } = useLocation();
  const [message, setMessage] = useState("");
  const hasNavigated = useRef(false);

  useEffect(() => {
    if (!hasNavigated.current) {
      hasNavigated.current = true;
      return;
    }

    const main = document.getElementById(MAIN_CONTENT_ID);
    if (!main) return;

    // Routes are code-split, so at this point `main` usually holds the
    // Suspense fallback and has no heading yet. Reading one frame later —
    // as this did originally — caught the fallback and announced a generic
    // string, and did so inconsistently: an already-cached chunk resolves
    // before the frame, a cold one does not. Wait for the heading instead.
    let announced = false;
    const announceHeading = () => {
      const heading = main.querySelector("h1")?.textContent?.trim();
      if (!heading) return false;
      setMessage(`${heading}. Page loaded.`);
      announced = true;
      return true;
    };

    if (announceHeading()) return;

    const observer = new MutationObserver(() => {
      if (announceHeading()) observer.disconnect();
    });
    observer.observe(main, { childList: true, subtree: true });

    // A route that renders no h1, or a chunk that never arrives, still owes
    // the user an announcement.
    const fallback = window.setTimeout(() => {
      observer.disconnect();
      if (!announced) setMessage("Page loaded.");
    }, 3000);

    return () => {
      observer.disconnect();
      window.clearTimeout(fallback);
    };
  }, [pathname]);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
    >
      {message}
    </div>
  );
}
