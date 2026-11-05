import { BrowserRouter, NavLink, Route, Routes } from "react-router";

import Home from "./pages/Home";
import ShoppingList from "./pages/ShoppingList";
import Search from "./pages/Search";
import StoreSelection from "./pages/StoreSelection";

import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="header">
          <NavLink to="/" className="logo">
            <span className="logo-icon">a.</span>
            agora
          </NavLink>

          <nav className="navigation" aria-label="Main navigation">
            <NavLink to="/" end>Home</NavLink>
            <NavLink to="/list">Shopping list</NavLink>
            <NavLink to="/search">Search</NavLink>
            <NavLink to="/stores">Supermarkets</NavLink>
          </nav>
        </header>

        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/list" element={<ShoppingList />} />
          <Route path="/search" element={<Search />} />
          <Route path="/stores" element={<StoreSelection />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
