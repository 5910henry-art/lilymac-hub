// src/index.js
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

// Tailwind compiled CSS
import "./styles/output.css";

// Lilymac custom styles
import "./index.css";

const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);


// Register the PWA service worker after the page has loaded.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { updateViaCache: "none" })
      .catch((error) => {
        console.error("LilyMac service worker registration failed:", error);
      });
  });
}
