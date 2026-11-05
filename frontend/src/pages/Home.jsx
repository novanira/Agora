import { useState } from "react";
import { Link, useNavigate } from "react-router";

const STORAGE_KEY = "agora-shopping-list";

function readSavedList() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export default function Home() {
  const [input, setInput] = useState("");
  const navigate = useNavigate();

  function startShoppingList(event) {
    event.preventDefault();

    const newItems = input.split(",").map((item) => item.trim()).filter(Boolean);
    if (newItems.length === 0) return;

    localStorage.setItem(STORAGE_KEY, JSON.stringify([...readSavedList(), ...newItems]));
    navigate("/list");
  }

  return (
    <main className="home">
      <div className="home-content">
        <div className="hero">
          <span className="eyebrow">A SMARTER WAY TO SHOP</span>
          <h1>
            Your whole grocery shop,
            <span> for less.</span>
          </h1>
          <p>
            Tell Agora what you need. We'll find the smartest way to shop
            across New Zealand's supermarkets.
          </p>
        </div>

        <form className="shopping-input" onSubmit={startShoppingList}>
          <input
            type="text"
            aria-label="Enter your shopping list"
            placeholder="Milk, eggs, bananas, bread..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit">Start my shopping list →</button>
        </form>

        <Link className="text-link" to="/search">
          Just comparing prices? Search products →
        </Link>
      </div>
    </main>
  );
}
