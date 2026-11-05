
import { useState } from "react";
import { Link } from "react-router";

export default function Search() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  function handleSearch(event) {
    event.preventDefault();
    setSubmitted(query.trim());
  }

  return (
    <main className="page">
      <div className="page-heading">
        <span className="eyebrow">PRODUCT DISCOVERY</span>

        <h1>Search products</h1>

        <p>
          Find products and compare prices across your
          favourite supermarkets.
        </p>
      </div>

      <form className="search-bar" onSubmit={handleSearch}>
        <input
          type="search"
          placeholder="Search for milk, eggs, bread..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <button type="submit">Search</button>
      </form>

      <div className="empty-card">
        <div className="empty-icon">⌖</div>

        <h2>Choose your supermarkets</h2>

        <p>
          Prices and product availability vary between stores.
          Select the branches you'd like Agora to compare.
        </p>

        {submitted && (
          <p className="search-notice">
            Search for "{submitted}" will be available once
            product search is connected.
          </p>
        )}

        <Link className="button" to="/stores">
          Choose supermarkets →
        </Link>

        <span className="helper-text">
          No account or location permission required
        </span>
      </div>
    </main>
  );
}
