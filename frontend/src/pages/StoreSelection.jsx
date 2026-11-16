
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import StoreMap from "../components/StoreMap.jsx";
import "./StoreSelection.css";

const SUPERMARKETS_STORAGE_KEY = "agora-selected-supermarkets";

const supermarkets = {
  woolworths: { name: "Woolworths", color: "#168B5B" },
  new_world: { name: "New World", color: "#D0473D" },
  paknsave: { name: "PAK'nSAVE", color: "#E0AE25" },
};

const returnPages = {
  "/": "Home",
  "/list": "Shopping List",
  "/search": "Search",
};

function readSavedSupermarkets() {
  const byKey = new Map();

  try {
    const saved = JSON.parse(localStorage.getItem(SUPERMARKETS_STORAGE_KEY) ?? "[]");
    if (!Array.isArray(saved)) return byKey;

    for (const store of saved) {
      if (
        typeof store?.chain === "string" &&
        Object.hasOwn(supermarkets, store.chain) &&
        typeof store.id === "string" &&
        typeof store.name === "string" &&
        typeof store.address === "string"
      ) {
        byKey.set(`${store.chain}:${store.id}`, store);
      }
    }
  } catch {
    // Start with an empty selection if browser storage is unavailable or invalid.
  }

  return byKey;
}

export default function StoreSelection() {
  const [locationInput, setLocationInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [savedSupermarkets, setSavedSupermarkets] = useState(readSavedSupermarkets);
  const locationInputRef = useRef(null);
  const savedHeadingRef = useRef(null);
  const location = useLocation();

  // Fall back to Shopping List if the user visits /stores directly.
  const from = location.state?.from;
  const returnPath = Object.hasOwn(returnPages, from)
    ? from
    : "/list";

  const returnLabel = returnPages[returnPath];

  useEffect(() => {
    try {
      localStorage.setItem(
        SUPERMARKETS_STORAGE_KEY,
        JSON.stringify([...savedSupermarkets.values()]),
      );
    } catch {
      // Keep the selection usable during this visit if browser storage is unavailable.
    }
  }, [savedSupermarkets]);

  function changeLocationInput(event) {
    const value = event.target.value;
    setLocationInput(value);
    if (!value.trim()) setSearchQuery("");
  }

  function searchForStores(event) {
    event.preventDefault();
    setSearchQuery(locationInput.trim());
  }

  function clearSearch(event) {
    event.preventDefault();
    setLocationInput("");
    setSearchQuery("");
    locationInputRef.current?.focus();
  }

  function showSavedSupermarkets() {
    const heading = savedHeadingRef.current;
    if (!heading) return;

    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ block: "start" });
  }

  function addSupermarket(chain, store, key) {
    const saved = {
      chain,
      id: String(store.id ?? store.store_id),
      name: (typeof store.name === "string" && store.name.trim()) || supermarkets[chain].name,
      address: typeof store.address === "string" ? store.address : "",
    };

    setSavedSupermarkets((current) => {
      if (current.has(key)) return current;
      return new Map(current).set(key, saved);
    });
  }

  function removeSupermarket(key) {
    setSavedSupermarkets((current) => {
      if (!current.has(key)) return current;

      const updated = new Map(current);
      updated.delete(key);
      return updated;
    });
  }

  return (
    <main className="page store-selection-page">
      <div className="stores-layout">
        <div className="stores-sidebar">
          <Link to={returnPath} className="button secondary store-back-link">
            <span aria-hidden="true">←</span>
            Back to {returnLabel}
          </Link>

          <div className="page-heading store-page-heading">
            <h1>Choose supermarkets</h1>

            <p>
              Find nearby supermarkets and choose the branches
              you're willing to visit.
            </p>
          </div>

          <div className="stores-panel">
            <form className="store-finder" onSubmit={searchForStores} onReset={clearSearch}>
              <label htmlFor="location">Find stores near</label>
              <input
                ref={locationInputRef}
                id="location"
                type="search"
                placeholder="Store name, suburb, city or postcode"
                value={locationInput}
                onChange={changeLocationInput}
              />
              <div className="store-finder__actions">
                <button type="submit">Search</button>
                <button
                  type="reset"
                  className="button secondary"
                  disabled={!locationInput && !searchQuery}
                >
                  Clear
                </button>
              </div>
            </form>
            <button
              type="button"
              className="saved-supermarkets-link"
              onClick={showSavedSupermarkets}
            >
              View selected supermarkets <span aria-hidden="true">↓</span>
            </button>
          </div>
        </div>

        <div className="map-placeholder agora-store-map-frame">
          <StoreMap
            searchQuery={searchQuery}
            onSelectStore={addSupermarket}
            onRemoveStore={removeSupermarket}
            addedStoreKeys={new Set(savedSupermarkets.keys())}
          />
        </div>
      </div>

      <section className="saved-supermarkets" aria-labelledby="saved-supermarkets">
        <h2 id="saved-supermarkets" ref={savedHeadingRef} tabIndex={-1}>
          Your supermarkets
        </h2>

        {savedSupermarkets.size === 0 ? (
          <p>Choose a pin on the map to add a branch.</p>
        ) : (
          <ul className="saved-supermarkets__list">
            {Array.from(savedSupermarkets, ([key, store]) => (
              <li className="store-card" key={key}>
                <span
                  className="store-dot"
                  aria-hidden="true"
                  style={{ background: supermarkets[store.chain].color }}
                />

                <div className="store-card__content">
                  <span>{store.name}</span>
                  {store.address && <div className="helper-text">{store.address}</div>}
                </div>
                <button
                  type="button"
                  className="button secondary store-card__remove"
                  aria-label={`Remove ${store.name}`}
                  onClick={() => removeSupermarket(key)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
