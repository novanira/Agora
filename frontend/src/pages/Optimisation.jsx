import { useMemo } from "react";
import { Link } from "react-router";
import { buildBasket, formatPrice, productSize, SHORTLIST_SIZE } from "../services/optimisation.js";
import { useBasketCatalog, useProductSelections } from "../services/useBasketCatalog.js";
import "./Optimisation.css";

function productLink(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:") return url.href;
  } catch {
    // Products can be displayed without a link.
  }
  return null;
}

function ProductList({ items }) {
  return (
    <ul className="optimisation-products">
      {items.map(({ key, query, count, product, unitCents, totalCents }) => {
        const link = productLink(product.product_url);
        const size = productSize(product);

        return (
          <li className="optimisation-product" key={key}>
            <div>
              <span className="optimisation-query">{query}{count > 1 && ` × ${count}`}</span>
              {link ? (
                <a href={link} target="_blank" rel="noreferrer">{product.name}</a>
              ) : (
                <strong>{product.name}</strong>
              )}
              {size && <span className="optimisation-note">{size}</span>}
            </div>
            <div>
              <strong>{formatPrice(totalCents)}</strong>
              {count > 1 && (
                <span className="optimisation-note">{formatPrice(unitCents)} each</span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function BasketResults({ basket, requestedCount }) {
  const { groups, branches, missing, itemCount, totalCents } = basket;

  return (
    <>
      <section className="optimisation-overview" aria-labelledby="optimisation-total">
        <div className="optimisation-total">
          <h2 id="optimisation-total">{itemCount === requestedCount ? "Estimated basket total" : "Estimated subtotal"}</h2>
          {itemCount > 0 && <strong className="optimisation-price">{formatPrice(totalCents)}</strong>}
          <p role="status">
            {itemCount} of {requestedCount} items found
            {groups.length > 0 && ` across ${groups.length} ${groups.length === 1 ? "store" : "stores"}`}
          </p>
        </div>
        <p className="optimisation-note">
          Agora compares branch prices for your chosen products. For items set to “Choose for me”,
          it compares the first {SHORTLIST_SIZE} available results at each branch. Prices for items sold by weight may vary.
        </p>
      </section>

      <div className="optimisation-results">
        <section className="optimisation-stores" aria-labelledby="optimisation-plan">
          <h2 id="optimisation-plan">{groups.length ? "Where to shop" : "No products found"}</h2>
          {groups.map((store) => (
            <article className="optimisation-panel optimisation-store" key={store.key}>
              <div className="optimisation-store-heading">
                <div>
                  <h3>{store.name}</h3>
                  {store.address && <p>{store.address}</p>}
                </div>
                <strong>{formatPrice(store.totalCents)}</strong>
              </div>
              <ProductList items={store.items} />
            </article>
          ))}

          {missing.length > 0 && (
            <section className="optimisation-panel optimisation-missing" aria-labelledby="optimisation-missing">
              <h2 id="optimisation-missing">Items without a recommendation</h2>
              <ul>
                {missing.map(({ key, query, count, reason }) => (
                  <li key={key}>
                    {query}{count > 1 && ` × ${count}`}
                    {reason === "selection-unavailable" && " · Chosen product unavailable"}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </section>

        {branches.length > 1 && (
          <section className="optimisation-panel optimisation-comparison" aria-labelledby="optimisation-comparison">
            <h2 id="optimisation-comparison">Shop at one store</h2>
            {branches.map((store) => (
              <details className="optimisation-option" key={store.key}>
                <summary>
                  <span>
                    {store.name}
                    <small className="optimisation-note optimisation-coverage">
                      {store.hasResults ? `${store.itemCount} of ${requestedCount} items found` : "No store results"}
                    </small>
                  </span>
                  {store.itemCount > 0 && (
                    <span>
                      {formatPrice(store.totalCents)}
                      {store.itemCount < requestedCount && (
                        <small className="optimisation-note optimisation-coverage">Subtotal</small>
                      )}
                    </span>
                  )}
                </summary>
                {store.address && <p className="optimisation-note">{store.address}</p>}
                {store.items.length > 0 && <ProductList items={store.items} />}
              </details>
            ))}
          </section>
        )}
      </div>
    </>
  );
}

export default function Optimisation() {
  const { items, stores, canCompare, catalog, error, retry } = useBasketCatalog();
  const [selections] = useProductSelections(items);
  const basket = useMemo(() => catalog ? buildBasket(catalog, selections) : null, [catalog, selections]);
  const requestedCount = items.reduce((total, item) => total + item.count, 0);

  return (
    <main className="page optimisation-page">
      <Link className="button secondary optimisation-back" to={canCompare ? "/product-selection" : "/list"}>
        <span aria-hidden="true">←</span> {canCompare ? "Edit product choices" : "Back to shopping list"}
      </Link>
      <div className="page-heading">
        <h1>Basket optimisation</h1>
        <p>Compare your shopping list across your chosen supermarkets.</p>
      </div>

      {!canCompare && (
        <section className="optimisation-panel">
          <h2>Get your basket ready</h2>
          {!items.length && <p>Add items to your shopping list to compare prices.</p>}
          {!stores.length && (
            <>
              <p>Choose at least one supermarket to compare.</p>
              <Link className="button" to="/stores" state={{ from: "/list" }}>Choose supermarkets</Link>
            </>
          )}
        </section>
      )}
      {canCompare && !basket && !error && (
        <div className="optimisation-panel" role="status">Comparing store prices…</div>
      )}
      {error && (
        <section className="optimisation-panel">
          <p role="alert">{error}</p>
          <button type="button" onClick={retry}>Try again</button>
        </section>
      )}
      {basket && <BasketResults basket={basket} requestedCount={requestedCount} />}
    </main>
  );
}
