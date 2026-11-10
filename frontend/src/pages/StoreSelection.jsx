
import { useState } from "react";
import { Link, useLocation } from "react-router";
import StoreSelectionMap from "../components/StoreSelectionMap.jsx";

const supermarkets = [
  { name: "Woolworths", color: "#168B5B" },
  { name: "New World", color: "#D0473D" },
  { name: "PAK'nSAVE", color: "#E0AE25" },
];

const returnPages = {
  "/": "Home",
  "/list": "Shopping List",
  "/search": "Search",
};

export default function StoreSelection() {
  const [locationInput, setLocationInput] = useState("");
  const location = useLocation();

  // Fall back to Shopping List if the user visits /stores directly.
  const from = location.state?.from;
  const returnPath = Object.hasOwn(returnPages, from)
    ? from
    : "/list";

  const returnLabel = returnPages[returnPath];

  return (
    <main className="page store-selection-page">
        <Link
            to={returnPath}
            className="text-link store-back-link"
        >
            ← Back to {returnLabel}
        </Link>

      <div className="page-heading store-page-heading">
        <span className="eyebrow">YOUR SUPERMARKETS</span>

        <h1>Choose supermarkets</h1>

        <p>
          Find nearby supermarkets and choose the branches
          you're willing to visit.
        </p>
      </div>

      <div className="stores-layout">
        <section className="stores-panel">
          <label htmlFor="location">Find stores near</label>

          <input
            id="location"
            type="search"
            placeholder="Enter suburb, city or postcode"
            value={locationInput}
            onChange={(event) =>
              setLocationInput(event.target.value)
            }
          />

          <h2>Supermarkets</h2>

          {supermarkets.map((store) => (
            <div className="store-card" key={store.name}>
              <span
                className="store-dot"
                style={{ background: store.color }}
              />

              <span>{store.name}</span>
            </div>
          ))}

          <p className="helper-text">
            Specific branches will be selectable here later.
          </p>

          <Link className="button" to={returnPath}>
            Return to {returnLabel} →
          </Link>
        </section>

        <div className="map-placeholder agora-store-map-frame">
          <StoreSelectionMap />
        </div>
      </div>
    </main>
  );
}
