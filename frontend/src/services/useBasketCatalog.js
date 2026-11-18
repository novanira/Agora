import { useEffect, useState } from "react";
import { fetchBasketCatalog, readBasketInputs } from "./optimisation.js";

const REQUEST_TIMEOUT = 90_000;
const CATALOG_MAX_AGE = 5 * 60_000;
const SELECTIONS_STORAGE_KEY = "agora-selected-products";

let cachedCatalog;
let savedSelections;

export function useBasketCatalog() {
  const [{ items, stores, key }] = useState(() => {
    const inputs = readBasketInputs();
    return { ...inputs, key: JSON.stringify(inputs) };
  });
  const [cached] = useState(() => (
    cachedCatalog?.key === key && Date.now() - cachedCatalog.loadedAt < CATALOG_MAX_AGE
      ? cachedCatalog.catalog
      : null
  ));
  const [result, setResult] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const canCompare = items.length > 0 && stores.length > 0;

  useEffect(() => {
    if (!canCompare || cached) return;

    const controller = new AbortController();
    const timeout = setTimeout(() => {
      controller.abort();
      setResult({ error: "The price comparison took too long. Please try again." });
    }, REQUEST_TIMEOUT);

    async function loadCatalog() {
      try {
        const catalog = await fetchBasketCatalog(items, stores, controller.signal);
        if (controller.signal.aborted) return;

        cachedCatalog = { key, catalog, loadedAt: Date.now() };
        setResult({ catalog });
      } catch {
        if (!controller.signal.aborted) {
          setResult({ error: "Couldn’t compare store prices. Please try again." });
        }
      } finally {
        clearTimeout(timeout);
      }
    }

    // Let the first development Strict Mode effect clean up before making a request.
    queueMicrotask(() => {
      if (!controller.signal.aborted) loadCatalog();
    });

    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt, cached, canCompare, items, key, stores]);

  function retry() {
    setResult(null);
    setAttempt((previous) => previous + 1);
  }

  return { items, stores, canCompare, catalog: cached ?? result?.catalog, error: result?.error, retry };
}

function readProductSelections(items) {
  if (!savedSelections) {
    savedSelections = new Map();
    try {
      const stored = JSON.parse(localStorage.getItem(SELECTIONS_STORAGE_KEY) ?? "{}");
      if (stored && typeof stored === "object" && !Array.isArray(stored)) {
        savedSelections = new Map(Object.entries(stored).filter(([, value]) => (
          typeof value?.key === "string" && Array.isArray(value.skuRefs)
        )));
      }
    } catch {
      // Keep selections in memory when storage is unavailable.
    }
  }

  return new Map(items.filter(({ key }) => savedSelections.has(key)).map(({ key }) => [key, savedSelections.get(key)]));
}

export function useProductSelections(items) {
  const [selections, setSelections] = useState(() => readProductSelections(items));

  function choose(itemKey, selection) {
    const next = new Map(selections);
    if (selection) {
      next.set(itemKey, selection);
    } else {
      next.delete(itemKey);
    }

    savedSelections = next;
    setSelections(next);
    try {
      localStorage.setItem(SELECTIONS_STORAGE_KEY, JSON.stringify(Object.fromEntries(next)));
    } catch {
      // The current browsing session can still use these selections.
    }
  }

  return [selections, choose];
}
