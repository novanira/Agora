import { useEffect } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  useLocation,
} from "react-router";

import Home from "./pages/Home";
import ShoppingList from "./pages/ShoppingList";
import Search from "./pages/Search";
import StoreSelection from "./pages/StoreSelection";
import ProductSelection from "./pages/ProductSelection";
import Optimisation from "./pages/Optimisation";

import "./App.css";

function AppLayout() {
  const { pathname } = useLocation();

  useEffect(() => {
    if (pathname === "/product-selection" || pathname === "/optimise") window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="app">
      <header className="header">
        <NavLink to="/" className="logo agora-logo">
          Agora
        </NavLink>

        <nav className="navigation">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/list">Shopping list</NavLink>
          <NavLink to="/search">Search</NavLink>
        </nav>
      </header>
      <div className="header-spacer" aria-hidden="true" />

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/list" element={<ShoppingList />} />
        <Route path="/search" element={<Search />} />
        <Route path="/stores" element={<StoreSelection />} />
        <Route path="/product-selection" element={<ProductSelection />} />
        <Route path="/optimise" element={<Optimisation />} />
      </Routes>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}