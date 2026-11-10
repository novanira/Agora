import { useEffect, useState } from "react";
import StoreMap from "./StoreMap.jsx";

const STORES_URL = "https://agora-72bb.onrender.com/stores/all";

export default function StoreSelectionMap({ onSelectStore }) {
  const [storesByChain, setStoresByChain] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadStores() {
      try {
        const response = await fetch(STORES_URL, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Could not load stores (HTTP ${response.status}).`);
        }

        const stores = await response.json();
        if (
          !Array.isArray(stores?.new_world) ||
          !Array.isArray(stores?.woolworths) ||
          !Array.isArray(stores?.paknsave)
        ) {
          throw new Error("The server returned an unexpected stores response.");
        }

        if (!controller.signal.aborted) setStoresByChain(stores);
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(error instanceof TypeError ? "Could not load stores." : error.message);
        }
      }
    }

    loadStores();
    return () => controller.abort();
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!storesByChain) return <p role="status">Loading stores…</p>;

  return <StoreMap storesByChain={storesByChain} onSelectStore={onSelectStore} />;
}
