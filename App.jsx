import "./App.css";
import { useState } from "react";
import Product from "./components/Product";

function App() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [budget, setBudget] = useState("");

  const searchProducts = async () => {
  const trimmedQuery = query.trim();

  if (!trimmedQuery) {
    setResults(null);
    setError("");
    setLoading(false);
    return;
  }

  setLoading(true);
  setError("");

  const currentQuery = trimmedQuery;

  try {
    const res = await fetch("http://127.0.0.1:8000/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        product_query: currentQuery,
        budget:
          budget && !isNaN(budget) && Number(budget) > 0
            ? Number(budget)
            : null, // ✅ SAFE FIX
      }),
    });

    const data = await res.json();

    // ✅ Handle backend 404 gracefully (NOT error)
    if (!res.ok) {
      if (res.status === 404) {
        setResults(null);
        setError(""); // ❌ remove "Load failed"
        return;
      }
      throw new Error(data.detail || "Backend error");
    }

    if (!query.trim() || currentQuery !== query.trim()) return;

    if (!data.top_picks || data.top_picks.length === 0) {
      setResults(null);
    } else {
      setResults(data);
    }

  } catch (err) {
    console.error(err);

    if (currentQuery === query.trim()) {
      setError(err.message || "Failed to fetch products");
      setResults(null);
    }
  } finally {
    if (currentQuery === query.trim()) {
      setLoading(false);
    }
  }
};

  const isSearched = query && (results || loading || error);

const availableProducts =
  results?.top_picks?.filter((item) => {
    const val = String(item.available).toLowerCase();
    return val === "true" || val === "1";
  }) || [];

const unavailableProducts =
  results?.top_picks?.filter((item) => {
    const val = String(item.available).toLowerCase();
    return !(val === "true" || val === "1");
  }) || [];

  return (
  <div id="center" className={isSearched ? "top" : "middle"}>

    {/* 🧠 HEADER */}
    <div className="header">
      <h1>AI-Based Online Product Comparison & Ranking System</h1>

      <div className="search-container glass">
  <input
    type="text"
    placeholder="Search for products like 'headphones under 3000'..."
    value={query}
    onChange={(e) => {
      const value = e.target.value;
      setQuery(value);

      setResults(null);
      setError("");
    }}
    onKeyDown={(e) => e.key === "Enter" && searchProducts()}
    className="search-input"
  />

  {/* 💰 ADD THIS LINE */}
  <input
    type="number"
    placeholder="Budget/optional"
    value={budget}
    onChange={(e) => setBudget(e.target.value)}
    className="budget-input"
  />

  <button
    onClick={searchProducts}
    disabled={loading}
    className="search-btn"
  >
    {loading ? "Searching..." : "Search"}
  </button>
</div>
    </div>

    {/* 🧭 EMPTY STATE */}
    {!query && (
      <div className="section narrow">
        <p className="loading muted">
          Try searching something like <b>“iPhone under 60k”</b>
        </p>
      </div>
    )}

    {/* ⏳ LOADING */}
    {loading && query && (
      <div className="section narrow">
        <p className="loading">
          Scanning the internet for best deals...
        </p>
      </div>
    )}

    {/* ❌ ERROR */}
    {error && query && (
      <div className="section narrow">
        <p className="error-message">{error}</p>
      </div>
    )}

    {/* 🚫 NO RESULTS */}
    {!loading && query && results === null && !error && (
      <div className="section narrow">
        <p className="error">
          No products found. Try a different search.
        </p>
      </div>
    )}

    {/* 🏆 BEST PRODUCT */}
    {query && results?.best_overall && (
      <div className="section glass">
        <div className="section-header">
          <h2>Best Choice</h2>
        </div>

        <div className="featured-wrapper">
         <Product
  name={results.best_overall.title}
  score={results.best_overall.score}
  price={results.best_overall.price}   
  link={results.best_overall.link}
  isBest={true}
  platform={results.best_overall.platform}
  in_stock={results.best_overall.available}
/>
        </div>
      </div>
    )}

    {/* 📊 TOP PICKS */}
    {query && availableProducts.length > 0 && (
  <div className="section glass">
    <div className="section-header">
      <h2>Top Picks</h2>
    </div>

    <div className="grid">
      {availableProducts.map((item, i) => {
  console.log("RAW in_stock:", item.available, typeof item.available);

  return (
    <Product
      key={i}
      name={item.title}
      score={item.score}
      price={item.price}
      link={item.link}
      platform={item.platform}
      in_stock={item.available}
    />
  );
})}
    </div>
  </div>
)}
    {/* 🧠 AI SUMMARY */}
    {query && results?.agent_summary && (
      <div className="section glass summary">
        <div className="section-header">
          <h2>AI Insight</h2>
        </div>

        <p className="summary-text">
          {results.agent_summary}
        </p>
      </div>
    )}

    {query && unavailableProducts.length > 0 && (
  <div className="section glass unavailable-section">
    <div className="section-header">
      <h2>Currently Unavailable</h2>
    </div>

    <div className="grid">
      {unavailableProducts.map((item, i) => {
  console.log("RAW in_stock:",item.available, typeof item.available);

  return (
    <Product
      key={i}
      name={item.title}
      score={item.score}
      price={item.price}
      link={item.link}
      platform={item.platform}
     in_stock={item.available}
    />
  );
})}
    </div>
  </div>
)}

  </div>
);
}

export default App;

