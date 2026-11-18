import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";
import {
  describeProductChoice,
  formatPrice,
  productSize,
  resolveProductChoice,
} from "../services/optimisation.js";
import { useBasketCatalog, useProductSelections } from "../services/useBasketCatalog.js";
import "./ProductSelection.css";

const PAGE_SIZE = 8;

function branchAvailability(store, offer) {
  if (offer?.available) return formatPrice(offer.unitCents);
  if (offer?.product.available === false) return "Out of stock";
  if (offer?.product.available === true) return "Price unavailable";
  return store.hasResults ? "No listing found" : "No store results";
}

function BranchOffers({ stores, choice }) {
  const size = productSize(choice.product);

  return (
    <div className="product-selection-offers">
      <strong>{choice.product.name}{size && ` · ${size}`}</strong>
      <ul className="product-selection-stores" aria-label={`Store availability for ${choice.product.name}`}>
        {stores.map((store) => (
          <li key={store.key}>
            <span>{store.name}{store.address && <small className="product-selection-muted">{store.address}</small>}</span>
            <strong>{branchAvailability(store, choice.offers.get(store.key))}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function imageUrl(value) {
  if (typeof value !== "string") return null;

  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function ProductImage({ src }) {
  const [failed, setFailed] = useState(false);

  return (
    <span className="product-selection-image">
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="product-selection-image-fallback">Image unavailable</span>
      )}
    </span>
  );
}

function ProductCard({ item, stores, option, selected, onSelect }) {
  const { product, offers, availableCount, lowestUnitCents } = option;
  const size = productSize(product);
  const onlyStore = availableCount === 1
    ? stores.find((store) => offers.get(store.key)?.available)
    : null;
  const src = imageUrl(product.image_url) ?? [...offers.values()]
    .map((offer) => imageUrl(offer.product.image_url))
    .find(Boolean);

  return (
    <label className="product-selection-option">
      <input
        type="radio"
        name={item.key}
        checked={selected}
        onChange={() => onSelect(item.key, describeProductChoice(option))}
      />
      <ProductImage key={src} src={src} />
      {selected && <span className="product-selection-check" aria-hidden="true">✓</span>}
      <span className="product-selection-option-content">
        <strong className="product-selection-name">{product.name}</strong>
        {size && <span className="product-selection-muted">{size}</span>}
      </span>
      <span>
        <strong className="product-selection-price">
          {availableCount > 1 && "From "}{formatPrice(lowestUnitCents)}
        </strong>
        <span className="product-selection-availability">
          {onlyStore?.name ?? `${availableCount} stores`}
        </span>
      </span>
    </label>
  );
}

function ProductQuery({ item, stores, choices, chosen, hasSelection, onSelect }) {
  const headingId = useId();
  const railRef = useRef(null);
  const firstNewIndex = useRef(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [scrollEdges, setScrollEdges] = useState({ previous: false, next: false });
  const options = choices.filter(({ availableCount }) => availableCount > 0);
  const term = filter.trim().toLowerCase();
  const matches = term
    ? options.filter(({ offers }) => [...offers.values()].some(({ product }) => product.name.toLowerCase().includes(term)))
    : options;
  const visible = matches.slice(0, limit);

  if (!term && chosen?.availableCount && !visible.includes(chosen)) visible.push(chosen);
  const visibleCount = visible.length;
  const hasMore = matches.length > limit;

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;

    if (firstNewIndex.current !== null) {
      const card = rail.children[firstNewIndex.current];
      firstNewIndex.current = null;
      if (card) {
        const offset = card.getBoundingClientRect().left - rail.firstElementChild.getBoundingClientRect().left;
        rail.scrollTo({ left: offset });
        if (!hasMore) card.querySelector("input")?.focus({ preventScroll: true });
      }
    }

    function updateScrollEdges() {
      const previous = rail.scrollLeft > 1;
      const next = rail.scrollWidth - rail.clientWidth - rail.scrollLeft > 1;
      setScrollEdges((current) => (
        current.previous === previous && current.next === next ? current : { previous, next }
      ));
    }

    updateScrollEdges();
    rail.addEventListener("scroll", updateScrollEdges, { passive: true });
    const observer = new ResizeObserver(updateScrollEdges);
    observer.observe(rail);

    return () => {
      rail.removeEventListener("scroll", updateScrollEdges);
      observer.disconnect();
    };
  }, [visibleCount, hasMore]);

  function updateFilter(value) {
    setFilter(value);
    setLimit(PAGE_SIZE);
    railRef.current?.scrollTo({ left: 0 });
  }

  function scrollProducts(direction) {
    const rail = railRef.current;
    if (!rail?.firstElementChild) return;

    const gap = parseFloat(getComputedStyle(rail).columnGap);
    const distance = rail.firstElementChild.getBoundingClientRect().width + gap;
    rail.scrollBy({
      left: direction * distance,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }

  return (
    <section className="product-selection-query" aria-labelledby={headingId}>
      <fieldset className="product-selection-fieldset">
        <legend className="product-selection-legend">Choose a product for {item.query}</legend>
        <div className="product-selection-query-header">
          <h2 id={headingId}>{item.query}{item.count > 1 && ` × ${item.count}`}</h2>
          <div className="product-selection-controls">
            {options.length > PAGE_SIZE && (
              <button
                type="button"
                className="product-selection-filter-toggle"
                aria-label={`Filter products for ${item.query}`}
                aria-expanded={filterOpen}
                onClick={() => {
                  if (filterOpen && filter) updateFilter("");
                  setFilterOpen(!filterOpen);
                }}
              >
                Filter
              </button>
            )}
            <label className="product-selection-auto">
              <input type="radio" name={item.key} checked={!hasSelection} onChange={() => onSelect(item.key)} />
              <span>Choose for me</span>
            </label>
            {visibleCount > 1 && (
              <div className="product-selection-scroll-buttons" hidden={!scrollEdges.previous && !scrollEdges.next}>
                <button
                  type="button"
                  className="product-selection-scroll-button"
                  aria-label={`Previous ${item.query} products`}
                  disabled={!scrollEdges.previous}
                  onClick={() => scrollProducts(-1)}
                >
                  <span aria-hidden="true">‹</span>
                </button>
                <button
                  type="button"
                  className="product-selection-scroll-button"
                  aria-label={`Next ${item.query} products`}
                  disabled={!scrollEdges.next}
                  onClick={() => scrollProducts(1)}
                >
                  <span aria-hidden="true">›</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {filterOpen && (
          <input
            type="search"
            className="product-selection-filter"
            value={filter}
            onChange={(event) => updateFilter(event.target.value)}
            placeholder="Filter by product name"
            aria-label={`Filter products for ${item.query}`}
            autoFocus
          />
        )}

        {visibleCount > 0 ? (
          <div className="product-selection-rail" ref={railRef}>
            {visible.map((option) => (
              <ProductCard
                key={option.key}
                item={item}
                stores={stores}
                option={option}
                selected={option.key === chosen?.key}
                onSelect={onSelect}
              />
            ))}
          </div>
        ) : (
          <p className="product-selection-muted">
            {term ? "No products match that filter." : "No available products were found for this item."}
          </p>
        )}

        {hasSelection && !chosen?.availableCount && (
          <p className="product-selection-muted" role="status">
            Your saved choice has no available offer. Choose another product or let Agora recommend one.
          </p>
        )}
        {chosen && <BranchOffers stores={stores} choice={chosen} />}

        {hasMore && (
          <div className="product-selection-pagination">
            <button
              type="button"
              className="button secondary product-selection-more"
              onClick={() => {
                firstNewIndex.current = limit;
                setLimit(limit + PAGE_SIZE);
              }}
            >
              Show more products
            </button>
          </div>
        )}
      </fieldset>
    </section>
  );
}

export default function ProductSelection() {
  const { items, stores, canCompare, catalog, error, retry } = useBasketCatalog();
  const [selections, choose] = useProductSelections(items);
  const chosenByQuery = new Map();
  let selectedCount = 0;
  if (catalog) {
    for (const [key, selection] of selections) {
      const chosen = resolveProductChoice(catalog.productsByQuery.get(key), selection);
      if (chosen) chosenByQuery.set(key, chosen);
      if (chosen?.availableCount) selectedCount += 1;
    }
  }

  return (
    <main className="page product-selection-page">
      <Link className="button secondary product-selection-back" to="/list">
        <span aria-hidden="true">←</span> Back to shopping list
      </Link>
      <div className="page-heading">
        <h1>Select products</h1>
        <p>Pick a product for each item or let Agora choose. Select a product to see its price and availability at each branch.</p>
      </div>

      {!canCompare && (
        <section className="product-selection-panel">
          <h2>Get your basket ready</h2>
          {!items.length && <p>Add items to your shopping list to see product options.</p>}
          {!stores.length && (
            <>
              <p>Choose at least one supermarket to see available products.</p>
              <Link className="button" to="/stores" state={{ from: "/list" }}>Choose supermarkets</Link>
            </>
          )}
        </section>
      )}
      {canCompare && !catalog && !error && (
        <div className="product-selection-panel" role="status">Finding products…</div>
      )}
      {error && (
        <section className="product-selection-panel">
          <p role="alert">{error}</p>
          <button type="button" onClick={retry}>Try again</button>
        </section>
      )}
      {catalog && (
        <div className="product-selection-form">
          <div className="product-selection-queries">
            {catalog.items.map((item) => (
              <ProductQuery
                key={item.key}
                item={item}
                stores={catalog.stores}
                choices={catalog.productsByQuery.get(item.key) ?? []}
                chosen={chosenByQuery.get(item.key)}
                hasSelection={selections.has(item.key)}
                onSelect={choose}
              />
            ))}
          </div>
          <div className="product-selection-actions">
            <p role="status">{selectedCount} of {items.length} search terms have a product selected.</p>
            <Link className="button" to="/optimise">Optimise Basket</Link>
          </div>
        </div>
      )}
    </main>
  );
}
