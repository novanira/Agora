
import { useState } from "react";
import { Link } from "react-router";

const supermarkets = [
  { name: "Woolworths", color: "#168B5B" },
  { name: "New World", color: "#D0473D" },
  { name: "PAK'nSAVE", color: "#E0AE25" },
];

export default function StoreSelection() {
  const [location, setLocation] = useState("");

  return (
    <main className="page">
      <div className="page-heading">
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
            value={location}
            onChange={(event) => setLocation(event.target.value)}
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

          <Link className="button" to="/search">
            Back to product search →
          </Link>
        </section>

        <div className="map-placeholder">
          <span className="map-icon">⌖</span>
          <h2>Supermarket map</h2>
          <p>Interactive map coming soon</p>
        </div>
      </div>
    </main>
  );
}
