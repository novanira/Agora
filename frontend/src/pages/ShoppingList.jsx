import { useEffect, useState } from "react";
import { Link } from "react-router";

const STORAGE_KEY = "agora-shopping-list";

function readSavedList() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export default function ShoppingList() {
  const [items, setItems] = useState(readSavedList);
  const [input, setInput] = useState("");

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }, [items]);

  function addItems(event) {
    event.preventDefault();
    const newItems = input.split(",").map((item) => item.trim()).filter(Boolean);
    if (newItems.length === 0) return;

    setItems((previous) => [...previous, ...newItems]);
    setInput("");
  }

  function removeItem(index) {
    setItems((previous) => previous.filter((_, i) => i !== index));
  }

  return (
    <main className="home started">
      <div className="home-content">
        <div className="list-heading">
          <span className="eyebrow">YOUR WORKSPACE</span>
          <h1>My shopping list</h1>
          <p>Everything you need, all in one place.</p>
        </div>

        <form className="shopping-input" onSubmit={addItems}>
          <input
            type="text"
            aria-label="Add shopping items"
            placeholder="Add milk, eggs, bread..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit">+ Add item</button>
        </form>

        <section className="shopping-list">
          <h2>Shopping items ({items.length})</h2>

          {items.length === 0 ? (
            <p style={{ color: "#728076" }}>
              Your list is empty. Add your first item above.
            </p>
          ) : (
            items.map((item, index) => (
              <div className="shopping-item" key={`${index}-${item}`}>
                <span className="item-circle" aria-hidden="true" />
                <span style={{ flex: 1 }}>{item}</span>
                <button
                  type="button"
                  className="button secondary"
                  style={{ padding: "7px 11px" }}
                  aria-label={`Remove ${item}`}
                  onClick={() => removeItem(index)}
                >
                  Remove
                </button>
              </div>
            ))
          )}

          <div className="page-actions">
            <Link className="button" to="/stores">
              Choose supermarkets
            </Link>
            <Link className="button secondary" to="/search">
              Search products
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
